"""Validate fiscal conversion plans and saved tables against their selected originals."""
from __future__ import annotations

import hashlib
import json
import ast
import re
from functools import lru_cache
from pathlib import Path

import jsonschema

from ingestion.paths import PIPELINE

HERE = Path(__file__).resolve().parent
INGESTION = HERE.parent
SCHEMA = HERE / 'manifest.schema.json'
JURISDICTIONS = HERE / 'jurisdictions'
BUCKET = 'fudoki-inputs'


def paths(root: Path | None = None) -> list[Path]:
    root = JURISDICTIONS if root is None else root
    return sorted(path for jurisdiction in root.iterdir() if jurisdiction.is_dir()
                  for year in jurisdiction.iterdir() if year.is_dir() and year.name.isdigit()
                  for path in year.rglob('*.json'))


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha_file(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def document_slot(target: dict) -> str:
    return (f'supplementary-{target["amendment_number"]}'
            if target['document_kind'] == 'supplementary' else target['document_kind'])


def manifest_path(target: dict, direction: str, root: Path | None = None) -> Path:
    root = JURISDICTIONS if root is None else root
    return root / target['jurisdiction'] / str(target['fiscal_year']) / document_slot(target) / f'{direction}.json'


def object_key(document: dict, table_id: str) -> str:
    target = document['target']
    return (f'fiscal/ingestion/{target["jurisdiction"]}/{target["fiscal_year"]}/'
            f'{document_slot(target)}/{document["direction"]}/{table_id}.parquet')


def code_path(value: str) -> Path:
    path = INGESTION / value
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(INGESTION.resolve()):
        raise ValueError(f'Converter/dependency is not an ingestion file: {value}')
    return path


def dependencies(conversion: dict) -> list[str]:
    pending = [conversion['converter'], conversion['options_schema'], *conversion['dependencies']]
    found = set()
    while pending:
        relative = pending.pop()
        if relative in found:
            continue
        found.add(relative)
        path = code_path(relative)
        if path.suffix != '.py':
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module, *[node.module + '.' + alias.name for alias in node.names]]
            elif isinstance(node, ast.ImportFrom) and node.level:
                base = list(path.relative_to(INGESTION).parent.parts)
                base = base[:len(base) - node.level + 1]
                modules = ['ingestion.' + '.'.join([*base, *(node.module or '').split('.')]).rstrip('.')]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith('ingestion.'):
                    modules = [node.value]
                if node.value.endswith(('.json', '.toml', '.swift')):
                    candidate = path.with_suffix(node.value) if node.value.startswith('.') else path.parent / node.value
                    if candidate.is_file() and candidate.resolve().is_relative_to(INGESTION.resolve()):
                        pending.append(str(candidate.relative_to(INGESTION)))
            for module in modules:
                if not module.startswith('ingestion.'):
                    continue
                target = INGESTION / Path(*module.split('.')[1:])
                candidate = target / '__init__.py' if target.is_dir() else target.with_suffix('.py')
                if candidate.is_file():
                    pending.append(str(candidate.relative_to(INGESTION)))
    return sorted(found)


@lru_cache(maxsize=1)
def validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def validate(document: dict, *, path: Path | None = None, check_code: bool = True) -> dict:
    validator().validate(document)
    if path is not None:
        expected_path = manifest_path(document['target'], document['direction'])
        if path.resolve() != expected_path.resolve():
            raise ValueError('Manifest location differs from its target/direction')
    conversions = {item['id']: item for item in document['conversions']}
    if len(conversions) != len(document['conversions']):
        raise ValueError('Duplicate conversion ID')
    expected: dict[str, str] = {}
    for conversion in conversions.values():
        inputs = conversion['inputs']
        if len({item['sha256'] for item in inputs}) != len(inputs):
            raise ValueError('Duplicate conversion original')
        for item in inputs:
            if len({scope['account'] for scope in item['scope']}) != len(item['scope']):
                raise ValueError('Duplicate account scope')
            for scope in item['scope']:
                ranges = scope.get('pages', [])
                previous = 0
                for first, last in ranges:
                    if first <= previous or last < first:
                        raise ValueError('PDF ranges must be ascending and non-overlapping')
                    previous = last
        for table in conversion['expected_tables']:
            if table['table_id'] in expected:
                raise ValueError('A table must have exactly one conversion owner')
            expected[table['table_id']] = conversion['id']
        if check_code:
            allowed = ('fiscal/layouts/', f'fiscal/jurisdictions/{document["target"]["jurisdiction"]}/layouts/')
            if not conversion['converter'].startswith(allowed) or not conversion['converter'].endswith('/convert.py'):
                raise ValueError('Converter must be a shared or target-local layout entry')
            if conversion['options_schema'] != str(Path(conversion['converter']).with_name('options.schema.json')):
                raise ValueError('Options schema must belong to the selected converter')
            for dependency in [conversion['converter'], *conversion['dependencies']]:
                code_path(dependency)
            options_schema = code_path(conversion['options_schema'])
            jsonschema.Draft202012Validator(json.loads(options_schema.read_text())).validate(conversion['options'])
    seen: set[str] = set()
    for table in document['tables']:
        ident = table['table_id']
        if ident in seen or expected.get(ident) != table['conversion_id']:
            raise ValueError('Duplicate, unexpected or incorrectly owned saved table')
        seen.add(ident)
        if table['object']['key'] != object_key(document, ident):
            raise ValueError('Saved table key differs from its target/direction/table ID')
        if len({column['name'] for column in table['schema']}) != len(table['schema']):
            raise ValueError('Duplicate Parquet column')
        if table['row_count'] == 0 and not table['empty_confirmed']:
            raise ValueError('Zero-row saved table needs an explicit empty-table confirmation')
        if 'origins' in table:
            shas = [origin['sha256'] for origin in table['origins']]
            wanted = {item['sha256'] for item in conversions[table['conversion_id']]['inputs']}
            if len(set(shas)) != len(shas) or set(shas) != wanted:
                raise ValueError('Saved original sizes differ from conversion inputs')
    if document['status'] == 'ready' and seen != set(expected):
        raise ValueError('Ready manifest must contain every expected table')
    if document['status'] == 'planned' and document['tables']:
        raise ValueError('A planned manifest cannot claim saved tables')
    return document


def read(path: Path, *, check_code: bool = True) -> dict:
    return validate(json.loads(path.read_text()), path=path, check_code=check_code)


def selection_for(document: dict) -> dict:
    target = document['target']
    ledger = json.loads((PIPELINE / 'source_selection' / f'{target["jurisdiction"]}.json').read_text())
    matches = [item for item in ledger['selections'] if item['target'] == target]
    if len(matches) != 1 or not matches[0].get('archive'):
        raise ValueError('Ingestion requires one selected, archived source target')
    selected = matches[0]
    if selected['selected_candidate_id'] != document['candidate_id']:
        raise ValueError('Selected candidate changed; update the conversion plan')
    if len(selected['candidates']) != 1 or selected['candidates'][0]['id'] != document['candidate_id']:
        raise ValueError('Selected source must contain exactly its chosen candidate')
    archive = selected['archive']
    files = selected['candidates'][0]['files']
    if archive['bucket'] != BUCKET or archive['candidate_id'] != document['candidate_id'] or len(files) != len(archive['files']):
        raise ValueError('Original archive differs from the selected candidate')
    shas = set()
    keys = set()
    for file, receipt in zip(files, archive['files'], strict=True):
        slot = f'fiscal/source-selection/{target["jurisdiction"]}/{target["fiscal_year"]}/{document_slot(target)}'
        if (file['sha256'] != receipt['sha256'] or file['sha256'] in shas or receipt['key'] in keys
                or not re.fullmatch(re.escape(slot) + r'(?:-[1-9][0-9]*)?\.' + re.escape(file['format']), receipt['key'])):
            raise ValueError('Original hash/key is not a unique selected archive object')
        shas.add(file['sha256'])
        keys.add(receipt['key'])
    return selected


def resolved_inputs(document: dict, conversion: dict, selection: dict | None = None) -> list[dict]:
    selected = selection if selection is not None else selection_for(document)
    candidate = next(item for item in selected['candidates'] if item['id'] == selected['selected_candidate_id'])
    origins = {file['sha256']: (file, receipt) for file, receipt in
               zip(candidate['files'], selected['archive']['files'], strict=True)}
    result = []
    for requested in conversion['inputs']:
        if requested['sha256'] not in origins:
            raise ValueError('Conversion original is not in the selected source')
        file, receipt = origins[requested['sha256']]
        if receipt['sha256'] != requested['sha256'] or file['format'] != requested['format']:
            raise ValueError('Original receipt/format differs from the plan')
        available = {scope['account']: scope for scope in (file['scope'] or [])
                     if scope['direction'] == document['direction']}
        for scope in requested['scope']:
            original_scope = available.get(scope['account'])
            if original_scope is None:
                raise ValueError('Account/direction is outside the selected scope')
            if file['format'] == 'pdf':
                for start, end in scope['pages']:
                    if not any(r['start'] <= start and end <= r['end'] for r in original_scope['pages']):
                        raise ValueError('PDF pages are outside the selected scope')
        result.append({**requested, 'bucket': selected['archive']['bucket'], 'key': receipt['key'],
                       'download_url': file['download_url'], 'pdf_type': file.get('pdf_type')})
    return result


def runtime(conversion: dict) -> dict[str, str]:
    import platform
    import sys
    import duckdb
    result = {'python': sys.version, 'duckdb': duckdb.__version__}
    if 'lib/vision_ocr.py' in dependencies(conversion):
        result.update(os=platform.platform(), os_build=platform.version())
    return result


def fingerprints(document: dict, conversions: list[dict] | None = None,
                 runtimes: dict[str, dict] | None = None) -> dict[str, str]:
    selected = selection_for(document)
    hashes = {}
    result = {}
    for conversion in document['conversions'] if conversions is None else conversions:
        origins = resolved_inputs(document, conversion, selected)
        files = dependencies(conversion)
        for path in files:
            if path not in hashes:
                hashes[path] = sha_file(code_path(path))
        material = {'target': document['target'], 'direction': document['direction'],
                    'candidate_id': document['candidate_id'], 'conversion': conversion,
                    'origins': [{k: item[k] for k in ('sha256', 'format', 'scope', 'pdf_type')} for item in origins],
                    'code': [{'path': path, 'sha256': hashes[path]} for path in files],
                    'runtime': runtime(conversion) if runtimes is None else runtimes[conversion['id']]}
        result[conversion['id']] = hashlib.sha256(canonical(material)).hexdigest()
    return result


def fingerprint(document: dict, conversion: dict, *, used_runtime: dict | None = None) -> str:
    return fingerprints(document, [conversion], None if used_runtime is None else {conversion['id']: used_runtime})[conversion['id']]


def require_current(document: dict) -> None:
    if document['status'] != 'ready':
        raise ValueError('Manifest has no complete saved table set')
    runtimes = {}
    for table in document['tables']:
        if 'runtime' in table:
            previous = runtimes.setdefault(table['conversion_id'], table['runtime'])
            if previous != table['runtime']:
                raise ValueError('One conversion has inconsistent execution conditions')
    values = fingerprints(document, runtimes=runtimes if len(runtimes) == len(document['conversions']) else None)
    for table in document['tables']:
        if table['input_fingerprint'] != values[table['conversion_id']]:
            raise ValueError(f'Stale saved table: {table["table_id"]}')


def write(path: Path, document: dict) -> None:
    import os
    import tempfile
    validate(document, path=path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
