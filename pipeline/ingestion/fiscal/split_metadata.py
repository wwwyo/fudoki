"""Move legacy dbt meanings out of saved ingestion manifests without rewriting tables."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import dbt_inputs
from ingestion.fiscal import manifest


def split(document: dict) -> tuple[dict, dict]:
    result = deepcopy(document)
    result['schema_version'] = 2
    bindings = {'schema_version': 1, 'target': document['target'],
                'direction': document['direction'], 'tables': []}
    for conversion in result['conversions']:
        for expected in conversion['expected_tables']:
            declaration = expected.pop('declaration')
            relative = expected.pop('legacy_path')
            bindings['tables'].append({'table_id': expected['table_id'],
                'raw_path': relative + '/data.parquet', 'declaration': declaration})
    if document['status'] == 'ready':
        manifest.require_current(document)
        runtimes = {table['conversion_id']: table['runtime'] for table in document['tables']}
        fingerprints = manifest.fingerprints(result, runtimes=runtimes)
        for table in result['tables']:
            table['input_fingerprint'] = fingerprints[table['conversion_id']]
        manifest.require_current(result)
    manifest.validate(result)
    dbt_inputs.validate(bindings, result)
    return result, bindings


def migrate(paths: list[Path] | None = None, *, apply: bool = False) -> dict:
    prepared = []
    for path in manifest.paths() if paths is None else paths:
        before = path.read_bytes()
        document = json.loads(before)
        if document['schema_version'] == 2:
            manifest.validate(document, path=path)
            if document['status'] == 'ready':
                manifest.require_current(document)
            dbt_inputs.read(document)
            continue
        result, bindings = split(document)
        manifest.validate(result, path=path)
        binding_path = dbt_inputs.path_for(result)
        if binding_path.exists() and json.loads(binding_path.read_text()) != bindings:
            raise ValueError('Existing dbt bindings differ; stop before changing manifests')
        prepared.append((path, before, result, bindings))
    if apply:
        # All documents and destinations are checked before publishing any change.
        for path, before, result, bindings in prepared:
            if path.read_bytes() != before:
                raise ValueError('Ingestion manifest changed during metadata migration')
            dbt_inputs.write(bindings, result)
            manifest.write(path, result)
    return {'status': 'applied' if apply else 'planned', 'manifests': len(prepared),
            'tables': sum(len(result['tables']) for _, _, result, _ in prepared)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, action='append')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(args.manifest, apply=args.apply)))


if __name__ == '__main__':
    main()
