"""Bind saved ingestion tables to dbt input paths."""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

import jsonschema
from referencing import Registry, Resource

from ingestion.fiscal import manifest
from ingestion.inputs import safe_relative

SCHEMA = Path(__file__).with_name('dbt') / 'inputs' / 'bindings.schema.json'


def path_for(document: dict, root: Path | None = None) -> Path:
    root = manifest.PIPELINE / 'dbt' / 'inputs' if root is None else root
    return manifest.manifest_path(document['target'], document['direction'], root)


@lru_cache(maxsize=1)
def validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA.read_text())
    ingestion_schema = manifest.validator().schema
    registry = Registry().with_resource(ingestion_schema['$id'], Resource.from_contents(ingestion_schema))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def validate(bindings: dict, document: dict) -> dict[str, dict]:
    validator().validate(bindings)
    if bindings['target'] != document['target'] or bindings['direction'] != document['direction']:
        raise ValueError('dbt bindings differ from their ingestion target/direction')
    entries = {table['table_id']: table for table in bindings['tables']}
    expected = {table['table_id'] for conversion in document['conversions']
                for table in conversion['expected_tables']}
    if len(entries) != len(bindings['tables']) or set(entries) != expected:
        raise ValueError('dbt bindings must match each ingestion table exactly once')
    paths = set()
    for conversion in document['conversions']:
        originals = {original['sha256'] for original in conversion['inputs']}
        editions = originals | {hashlib.sha256(manifest.canonical(sorted(originals))).hexdigest()}
        for expected_table in conversion['expected_tables']:
            relative = entries[expected_table['table_id']]['raw_path']
            path = PurePosixPath(safe_relative(relative))
            parts = dict(part.split('=', 1) for part in path.parts if '=' in part)
            target = document['target']
            kind = 'budget' if target['document_kind'] == 'initial' else target['document_kind']
            if (path.name != 'data.parquet' or relative in paths
                    or parts.get('jurisdiction') != target['jurisdiction']
                    or parts.get('year') != str(target['fiscal_year'])
                    or parts.get('document_kind') != kind
                    or parts.get('direction') != document['direction']
                    or parts.get('edition') not in editions):
                raise ValueError('dbt input path differs from its saved table scope')
            paths.add(relative)
    return entries


def read(document: dict, root: Path | None = None) -> dict[str, dict]:
    try:
        bindings = json.loads(path_for(document, root).read_text())
    except FileNotFoundError:
        if any(item['converter'] == 'fiscal/layouts/retained/convert.py' for item in document['conversions']):
            raise ValueError('Retained tables require dbt input bindings')
        return {}
    return validate(bindings, document)


def write(bindings: dict, document: dict, root: Path | None = None, *, extend: bool = False) -> None:
    validate(bindings, document)
    path = path_for(document, root)
    try:
        existing = json.loads(path.read_text())
    except FileNotFoundError:
        pass
    else:
        if existing == bindings:
            return
        validator().validate(existing)
        previous = {table['table_id']: table for table in existing['tables']}
        current = {table['table_id']: table for table in bindings['tables']}
        if (not extend or existing['target'] != bindings['target']
                or existing['direction'] != bindings['direction']
                or len(previous) != len(existing['tables'])
                or not all(current.get(ident) == table for ident, table in previous.items())):
            raise ValueError('Existing dbt bindings differ; do not replace them implicitly')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(bindings, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--manifest', type=Path, action='append')
    args = parser.parse_args()
    paths = manifest.paths() if args.manifest is None else args.manifest
    count = 0
    for path in paths:
        count += len(read(manifest.read(path)))
    print(json.dumps({'manifests': len(paths), 'bound_tables': count}))


if __name__ == '__main__':
    main()
