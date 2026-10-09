"""Schema-validated CSV/PDF conversion, private storage and bounded summaries."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import duckdb

from ingestion.fiscal import manifest
from ingestion.fiscal.storage import fetch, save, cleanup, verify


def inspect_table(path: Path, metadata: dict | None = None) -> int:
    with duckdb.connect() as con:
        count = con.execute('select count(*) from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchone()[0]
        columns = con.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    if len({row[0] for row in columns}) != len(columns):
        raise ValueError('Duplicate Parquet column')
    if metadata is not None:
        manifest.validate_metadata(metadata, [row[0] for row in columns])
    return count


def originals(path: Path, output: Path, *, remote: bool = False) -> dict:
    document = manifest.read(path)
    selection = manifest.selection_for(document)
    files = {}
    for conversion in document['conversions']:
        for item in manifest.resolved_inputs(document, conversion, selection):
            if item['sha256'] not in files:
                files[item['sha256']] = str(fetch(item, remote=remote))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(files, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return {'originals': len(files), 'inputs': str(output)}


def table_receipt(document: dict, conversion: dict, table_id: str, path: Path, *, input_fingerprint: str | None = None,
                  metadata: dict | None = None) -> dict:
    fingerprint = input_fingerprint or manifest.fingerprint(document, conversion)
    sha = manifest.sha_file(path)
    previous = next((table for table in document['tables'] if table['table_id'] == table_id), None)
    if metadata is None and previous is not None and 'metadata' in previous:
        if previous['input_fingerprint'] != fingerprint or previous['object']['sha256'] != sha:
            raise ValueError('Changed annotated table requires metadata from its converter')
        metadata = previous['metadata']
    count = inspect_table(path, metadata)
    if count == 0:
        raise ValueError('Empty output is not supported')
    result = {'table_id': table_id, 'conversion_id': conversion['id'],
            'input_fingerprint': fingerprint,
            'object': {'key': manifest.object_key(document, table_id),
                       'sha256': sha, 'bytes': path.stat().st_size},
            'row_count': count}
    if metadata is not None:
        result['metadata'] = deepcopy(metadata)
    return result


def convert(path: Path, local_files: dict[str, str], output: Path, *, remote: bool = False,
            conversion_ids: list[str] | None = None, extend_plan: Path | None = None) -> dict:
    document = manifest.read(path)
    original_bytes = None
    if extend_plan is not None:
        original_bytes = path.read_bytes()
        if json.loads(original_bytes) != document:
            raise ValueError('Saved manifest changed while preparing extension')
        plan = manifest.validate(json.loads(extend_plan.read_text()), path=path)
        old = document['conversions']
        if (plan['target'] != document['target'] or plan['direction'] != document['direction']
                or plan['tables'] or len(plan['conversions']) != len(old) + 1
                or plan['conversions'][:-1] != old):
            raise ValueError('Extension must append one conversion to the same target/direction with unchanged definitions and tables=[]')
        added = plan['conversions'][-1]
        if len(added['expected_tables']) != 1:
            raise ValueError('Extension requires exactly one new expected table')
        if conversion_ids is not None and conversion_ids != [added['id']]:
            raise ValueError('Extension conversion selection must be the one new ID')
        manifest.require_current(document)
        retained_tables = deepcopy(document['tables'])
        document = deepcopy(plan)
        document['tables'] = retained_tables
        conversion_ids = [added['id']]
    selection = manifest.selection_for(document)
    all_ids = {conversion['id'] for conversion in document['conversions']}
    chosen = set(conversion_ids) if conversion_ids is not None else all_ids
    if not chosen or not chosen <= all_ids:
        raise ValueError('Unknown or empty conversion selection')
    before = manifest.fingerprints(document)
    output.mkdir(parents=True, exist_ok=False)
    outputs = {}
    tables = []
    for conversion in document['conversions']:
        if conversion['id'] not in chosen:
            retained = [table for table in document['tables'] if table['conversion_id'] == conversion['id']]
            if {table['table_id'] for table in retained} != {item['table_id'] for item in conversion['expected_tables']}:
                raise ValueError('Partial conversion cannot omit unsaved expected tables')
            for table in retained:
                if table['input_fingerprint'] != before[conversion['id']]:
                    raise ValueError('An untouched table is stale; include its conversion')
                stored = fetch(table['object'], remote=remote)
                if extend_plan is not None:
                    verify(stored, table['object'])
                count = inspect_table(stored, table.get('metadata'))
                if extend_plan is not None and count != table['row_count']:
                    raise ValueError('Retained table row count differs from its receipt')
            tables.extend(retained)
            continue
        inputs = manifest.resolved_inputs(document, conversion, selection)
        for item in inputs:
            source = Path(local_files[item['sha256']])
            if manifest.sha_file(source) != item['sha256']:
                raise ValueError('Supplied original differs from the selected byte identity')
            item['path'] = source
            item['target'] = document['target']
            item['direction'] = document['direction']
        code = manifest.code_path(conversion['converter'])
        spec = importlib.util.spec_from_file_location('ingestion_converter_' + conversion['id'], code)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        generated = module.convert(inputs, output, conversion['options'])
        expected = {item['table_id'] for item in conversion['expected_tables']}
        if not isinstance(generated, dict) or set(generated) != expected:
            raise ValueError('Converter did not produce exactly its declared tables')
        for ident, file in generated.items():
            metadata = None
            if isinstance(file, dict):
                if 'path' not in file or set(file).difference({'path', 'metadata'}):
                    raise ValueError('Converter table descriptor requires path and optional metadata only')
                metadata = file.get('metadata')
                if 'metadata' in file and metadata is None:
                    raise ValueError('Converter metadata must be an object')
                file = file['path']
            file = Path(file)
            if not file.resolve().is_relative_to(output.resolve()) or file.is_symlink():
                raise ValueError('Converter output is outside the candidate directory')
            outputs[ident] = file
            tables.append(table_receipt(document, conversion, ident, file,
                                        input_fingerprint=before[conversion['id']], metadata=metadata))
    result = deepcopy(document)
    result['tables'] = tables
    manifest.validate(result)
    used_originals = {item['sha256'] for conversion in document['conversions']
                      if conversion['id'] in chosen for item in conversion['inputs']}
    for sha in sorted(used_originals):
        if manifest.sha_file(Path(local_files[sha])) != sha:
            raise ValueError('Supplied original changed during conversion')
    if before != manifest.fingerprints(result):
        raise ValueError('Input conditions changed during conversion')
    candidate = output / 'manifest.json'
    # Candidate is not a saved manifest; it stays outside the Git registry.
    candidate.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if remote:
        if original_bytes is not None and path.read_bytes() != original_bytes:
            raise ValueError('Saved manifest changed before extension upload')
        for table in tables:
            if table['conversion_id'] not in chosen:
                continue
            save(result, table, outputs[table['table_id']], remote=True)
        manifest.require_current(result)
        if original_bytes is not None and path.read_bytes() != original_bytes:
            raise ValueError('Saved manifest changed before extension registration')
        manifest.write(path, result)
        cleanup(result)
    return {'status': 'saved' if remote else 'candidate', 'tables': len(tables),
            'rows': sum(t['row_count'] for t in tables), 'candidate': str(candidate)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('schema')
    origin = sub.add_parser('originals', help='Restore selected originals and write a local input-path map')
    origin.add_argument('--manifest', type=Path, required=True)
    origin.add_argument('--output', type=Path, required=True)
    origin.add_argument('--remote', action='store_true')
    check = sub.add_parser('check')
    check.add_argument('--manifest', type=Path)
    run = sub.add_parser('convert')
    run.add_argument('--manifest', type=Path, required=True)
    run.add_argument('--inputs', type=Path, required=True, help='JSON: original SHA-256 to local file path')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--remote', action='store_true')
    run.add_argument('--conversion', action='append', help='Re-run these conversion IDs, preserving all untouched tables')
    run.add_argument('--extend-plan', type=Path,
                     help='JSON in the existing manifest schema: same target/direction, unchanged existing conversions plus one new conversion/table, tables=[]. Retains verified saved tables and converts/uploads only the new table; registers only after full success. Local mode writes the candidate only.')
    restore = sub.add_parser('restore')
    restore.add_argument('--manifest', type=Path, required=True)
    restore.add_argument('--remote', action='store_true')
    clean = sub.add_parser('cleanup')
    clean.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'schema':
        print(manifest.SCHEMA.read_text())
    elif args.command == 'check':
        paths = [args.manifest] if args.manifest else manifest.paths()
        count = ready = tables = 0
        for path in paths:
            document = manifest.read(path)
            for conversion in document['conversions']:
                manifest.resolved_inputs(document, conversion)
            if document['tables']:
                manifest.require_current(document)
                ready += 1
            count += 1
            tables += len(document['tables'])
        print(json.dumps({'valid': True, 'manifests': count, 'ready': ready, 'saved_tables': tables}))
    elif args.command == 'originals':
        print(json.dumps(originals(args.manifest, args.output, remote=args.remote)))
    elif args.command == 'convert':
        print(json.dumps(convert(args.manifest, json.loads(args.inputs.read_text()), args.output,
                                 remote=args.remote, conversion_ids=args.conversion, extend_plan=args.extend_plan)))
    elif args.command == 'restore':
        document = manifest.read(args.manifest)
        manifest.require_current(document)
        for table in document['tables']:
            restored = fetch(table['object'], remote=args.remote)
            inspect_table(restored, table.get('metadata'))
        print(json.dumps({'restored': len(document['tables'])}))
    else:
        print(json.dumps({'removed': cleanup(manifest.read(args.manifest))}))


if __name__ == '__main__':
    main()
