"""Prepare dbt inputs from jurisdiction ingestion JSON and saved Parquet."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from ingestion.fiscal import manifest
from ingestion.fiscal.storage import fetch, verify
from ingestion.paths import CACHE
import dbt_inputs


def inventory(paths: list[Path] | None = None, *, for_build: bool = False) -> list[dict]:
    result = []
    for path in manifest.paths() if paths is None else paths:
        document = manifest.read(path)
        manifest.require_current(document)
        selection = manifest.selection_for(document)
        originals = {conversion['id']: manifest.resolved_inputs(document, conversion, selection)
                     for conversion in document['conversions']}
        item = {'manifest': str(path.resolve()), 'document': document, 'inputs': originals}
        if for_build:
            item['bindings'] = dbt_inputs.read(document)
        result.append(item)
    if not result or len({item['manifest'] for item in result}) != len(result):
        raise ValueError('Build inputs require a nonempty, unique set of ready manifests')
    return sorted(result, key=lambda item: item['manifest'])


def raw_path(document: dict, conversion: dict, expected: dict, binding: dict | None = None) -> str:
    if binding is not None:
        return binding['raw_path']
    target = document['target']
    originals = {item['sha256'] for item in conversion['inputs']}
    kind = 'budget' if target['document_kind'] == 'initial' else target['document_kind']
    edition = next(iter(originals)) if len(originals) == 1 else hashlib.sha256(manifest.canonical(sorted(originals))).hexdigest()
    return (f'jurisdiction={target["jurisdiction"]}/year={target["fiscal_year"]}/'
            f'document_kind={kind}/edition={edition}/direction={document["direction"]}/'
            f'table={expected["table_id"]}/data.parquet')


def tables(items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items:
        document = item['document']
        saved = {table['table_id']: table for table in document['tables']}
        for conversion in document['conversions']:
            for expected in conversion['expected_tables']:
                binding = item.get('bindings', {}).get(expected['table_id'])
                relative = raw_path(document, conversion, expected, binding)
                if relative in seen:
                    raise ValueError('Multiple saved tables own one dbt input path')
                seen.add(relative)
                result.append({'manifest': item['manifest'], 'target': document['target'],
                    'direction': document['direction'], 'raw_path': relative,
                    'table': saved[expected['table_id']],
                    'inputs': item['inputs'][conversion['id']]})
    return result


def restore(paths: list[Path] | None = None, *, remote: bool = False) -> dict:
    items = inventory(paths)
    values = [table for item in items for table in item['document']['tables']]
    for table in values:
        fetch(table['object'], remote=remote)
    return {'manifests': len(items), 'tables': len(values)}


def prepare(paths: list[Path] | None = None, *, cache: Path | None = None) -> dict:
    items = inventory(paths, for_build=True)
    values = tables(items)
    material = {'manifests': [{'document': item['document'], 'bindings': item['bindings'],
                               'inputs': item['inputs']} for item in items]}
    fingerprint = hashlib.sha256(manifest.canonical(material)).hexdigest()
    root = CACHE / 'inputs' if cache is None else cache
    destination = root / fingerprint
    root.mkdir(parents=True, exist_ok=True)
    expected = {item['raw_path']: item['table']['object'] for item in values}
    catalog_body = {'schema_version': 1, 'input_fingerprint': fingerprint,
                    'manifests': items, 'tables': values}
    if destination.exists():
        catalog = json.loads((destination / 'catalog.json').read_text())
        if catalog != catalog_body:
            raise ValueError('Existing build input catalog differs')
        actual = {str(path.relative_to(destination/'raw')) for path in (destination/'raw').rglob('*.parquet')}
        if actual != set(expected):
            raise ValueError('Existing build input snapshot has missing or additional tables')
        for relative, reference in expected.items():
            verify(destination / 'raw' / relative, reference)
    else:
        with tempfile.TemporaryDirectory(prefix='prepare-', dir=root) as temporary:
            staged = Path(temporary) / 'snapshot'
            (staged / 'raw').mkdir(parents=True)
            for item in values:
                source = fetch(item['table']['object'])
                target = staged / 'raw' / item['raw_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                verify(target, item['table']['object'])
            (staged / 'catalog.json').write_text(json.dumps(catalog_body, ensure_ascii=False, indent=2) + '\n')
            if manifest.canonical(inventory(paths, for_build=True)) != manifest.canonical(items):
                raise ValueError('Ingestion references changed while preparing build inputs')
            staged.rename(destination)
    if manifest.canonical(inventory(paths, for_build=True)) != manifest.canonical(items):
        raise ValueError('Ingestion references changed while preparing build inputs')
    return {'inputFingerprint': fingerprint, 'catalog': str(destination / 'catalog.json'),
            'inputs': str(destination / 'raw'),
            'tables': len(values), 'manifests': len(items)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    restoring = sub.add_parser('restore')
    restoring.add_argument('--remote', action='store_true')
    preparing = sub.add_parser('prepare')
    for command in (restoring, preparing):
        command.add_argument('--manifest', type=Path, action='append')
    args = parser.parse_args()
    result = restore(args.manifest, remote=args.remote) if args.command == 'restore' else prepare(args.manifest)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
