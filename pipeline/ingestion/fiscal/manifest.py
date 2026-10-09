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


def options_schema(conversion: dict) -> str:
    return str(Path(conversion['converter']).with_name('options.schema.json'))


def dependencies(conversion: dict) -> list[str]:
    pending = [conversion['converter'], options_schema(conversion)]
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
                module = 'ingestion.' + '.'.join([*base, *node.module.split('.')] if node.module else base)
                modules = [module, *[module + '.' + alias.name for alias in node.names]]
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


def validate_metadata(metadata: dict, columns: list[str] | None = None) -> None:
    """Check original annotations against actual top-level Parquet columns."""
    validator().evolve(schema={'$ref': '#/$defs/table_metadata'}).validate(metadata)
    referenced = set()
    for kind in ('units', 'notes'):
        for item in metadata.get(kind, []):
            if item['scope']['kind'] == 'columns':
                referenced.update(item['scope']['columns'])
    owned = set()
    for context in metadata.get('column_contexts', []):
        if owned.intersection(context['columns']):
            raise ValueError('A column must have exactly one declared context')
        owned.update(context['columns'])
        referenced.update(context['columns'])
        referenced.update(context['grain_columns'])
    if columns is not None:
        missing = referenced.difference(columns)
        if missing:
            raise ValueError(f'Metadata references missing Parquet columns: {sorted(missing)}')


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
        for table in conversion['expected_tables']:
            if table['table_id'] in expected:
                raise ValueError('A table must have exactly one conversion owner')
            expected[table['table_id']] = conversion['id']
        if check_code:
            allowed = ('fiscal/layouts/', f'fiscal/jurisdictions/{document["target"]["jurisdiction"]}/layouts/')
            if not conversion['converter'].startswith(allowed) or not conversion['converter'].endswith('/convert.py'):
                raise ValueError('Converter must be a shared or target-local layout entry')
            code_path(conversion['converter'])
            schema_path = code_path(options_schema(conversion))
            jsonschema.Draft202012Validator(json.loads(schema_path.read_text())).validate(conversion['options'])
    seen: set[str] = set()
    for table in document['tables']:
        ident = table['table_id']
        if ident in seen or expected.get(ident) != table['conversion_id']:
            raise ValueError('Duplicate, unexpected or incorrectly owned saved table')
        seen.add(ident)
        if table['object']['key'] != object_key(document, ident):
            raise ValueError('Saved table key differs from its target/direction/table ID')
        if 'metadata' in table:
            validate_metadata(table['metadata'])
    if seen and seen != set(expected):
        raise ValueError('Saved manifest must contain every expected table')
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
    if len(selected['candidates']) != 1 or selected['candidates'][0]['id'] != selected['selected_candidate_id']:
        raise ValueError('Selected source must contain exactly its chosen candidate')
    archive = selected['archive']
    files = selected['candidates'][0]['files']
    if archive['bucket'] != BUCKET or archive['candidate_id'] != selected['selected_candidate_id'] or len(files) != len(archive['files']):
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
        if receipt['sha256'] != requested['sha256']:
            raise ValueError('Original receipt differs from the plan')
        scopes = [{key: value for key, value in scope.items() if key != 'direction'}
                  for scope in (file['scope'] or []) if scope['direction'] == document['direction']]
        if not scopes or len({scope['account'] for scope in scopes}) != len(scopes):
            raise ValueError('Selected original needs unique account scopes for this direction')
        for scope in scopes:
            if file['format'] == 'pdf':
                ranges = [[r['start'], r['end']] for r in scope['pages']]
                previous = 0
                for first, last in ranges:
                    if first <= previous or last < first:
                        raise ValueError('PDF ranges must be ascending and non-overlapping')
                    previous = last
                if not ranges:
                    raise ValueError('Selected PDF scope needs pages')
                scope['pages'] = ranges
        result.append({'sha256': requested['sha256'], 'format': file['format'], 'scope': scopes,
                       'bucket': selected['archive']['bucket'], 'key': receipt['key'],
                       'download_url': file['download_url'], 'pdf_type': file.get('pdf_type')})
    return result


def fingerprints(document: dict, conversions: list[dict] | None = None) -> dict[str, str]:
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
                    'conversion': conversion,
                    'origins': [{k: item[k] for k in ('sha256', 'format', 'scope', 'pdf_type')} for item in origins],
                    'code': [{'path': path, 'sha256': hashes[path]} for path in files]}
        result[conversion['id']] = hashlib.sha256(canonical(material)).hexdigest()
    return result


def fingerprint(document: dict, conversion: dict) -> str:
    return fingerprints(document, [conversion])[conversion['id']]


def require_current(document: dict) -> None:
    if not document['tables']:
        raise ValueError('Manifest has no complete saved table set')
    values = fingerprints(document)
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
