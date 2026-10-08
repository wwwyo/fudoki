"""Schema-validated CSV/PDF conversion, private storage and bounded summaries."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import duckdb

from ingestion.fiscal import manifest
from ingestion.fiscal.storage import fetch, save, cleanup


def inspect_table(path: Path) -> tuple[int, list[dict]]:
    with duckdb.connect() as con:
        count = con.execute('select count(*) from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchone()[0]
        columns = con.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    return count, [{'name': row[0], 'type': row[1]} for row in columns]


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


def table_receipt(document: dict, conversion: dict, table_id: str, path: Path, *, empty_confirmed: bool = False,
                  input_fingerprint: str | None = None, origins: list[dict] | None = None) -> dict:
    count, schema = inspect_table(path)
    if count == 0 and not empty_confirmed:
        raise ValueError('Empty output requires explicit confirmation of the printed empty table')
    result = {'table_id': table_id, 'conversion_id': conversion['id'],
            'input_fingerprint': input_fingerprint or manifest.fingerprint(document, conversion),
            'object': {'bucket': manifest.BUCKET, 'key': manifest.object_key(document, table_id),
                       'sha256': manifest.sha_file(path), 'bytes': path.stat().st_size},
            'row_count': count, 'schema': schema, 'empty_confirmed': empty_confirmed}
    result['runtime'] = manifest.runtime(conversion)
    if origins is not None:
        result['origins'] = origins
    return result


def convert(path: Path, local_files: dict[str, str], output: Path, *, remote: bool = False,
            conversion_ids: list[str] | None = None) -> dict:
    document = manifest.read(path)
    selection = manifest.selection_for(document)
    all_ids = {conversion['id'] for conversion in document['conversions']}
    chosen = set(conversion_ids) if conversion_ids is not None else all_ids
    if not chosen or not chosen <= all_ids:
        raise ValueError('Unknown or empty conversion selection')
    used_runtimes = {}
    for conversion in document['conversions']:
        ident = conversion['id']
        if ident in chosen:
            used_runtimes[ident] = manifest.runtime(conversion)
        else:
            saved = [t for t in document['tables'] if t['conversion_id'] == ident]
            if not saved or any(t.get('runtime') != saved[0].get('runtime') for t in saved):
                raise ValueError('Untouched conversion has no consistent execution conditions')
            used_runtimes[ident] = saved[0]['runtime']
    before = manifest.fingerprints(document, runtimes=used_runtimes)
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
                outputs[table['table_id']] = fetch(table['object'], remote=remote)
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
            file = Path(file)
            if not file.resolve().is_relative_to(output.resolve()) or file.is_symlink():
                raise ValueError('Converter output is outside the candidate directory')
            outputs[ident] = file
            tables.append(table_receipt(document, conversion, ident, file, input_fingerprint=before[conversion['id']],
                                        origins=[{'sha256': item['sha256'], 'bytes': item['path'].stat().st_size} for item in inputs]))
    result = deepcopy(document)
    result.update(status='ready', tables=tables)
    manifest.validate(result)
    used_originals = {item['sha256'] for conversion in document['conversions']
                      if conversion['id'] in chosen for item in conversion['inputs']}
    for sha in sorted(used_originals):
        if manifest.sha_file(Path(local_files[sha])) != sha:
            raise ValueError('Supplied original changed during conversion')
    if before != manifest.fingerprints(result, runtimes=used_runtimes):
        raise ValueError('Input conditions changed during conversion')
    candidate = output / 'manifest.json'
    # Candidate is not a saved manifest; it stays outside the Git registry.
    candidate.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if remote:
        for table in tables:
            save(result, table, outputs[table['table_id']], remote=True)
        manifest.require_current(result)
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
            if document['status'] == 'ready':
                manifest.require_current(document)
                ready += 1
            count += 1
            tables += len(document['tables'])
        print(json.dumps({'valid': True, 'manifests': count, 'ready': ready, 'saved_tables': tables}))
    elif args.command == 'originals':
        print(json.dumps(originals(args.manifest, args.output, remote=args.remote)))
    elif args.command == 'convert':
        print(json.dumps(convert(args.manifest, json.loads(args.inputs.read_text()), args.output,
                                 remote=args.remote, conversion_ids=args.conversion)))
    elif args.command == 'restore':
        document = manifest.read(args.manifest)
        manifest.require_current(document)
        for table in document['tables']:
            fetch(table['object'], remote=args.remote)
        print(json.dumps({'restored': len(document['tables'])}))
    else:
        print(json.dumps({'removed': cleanup(manifest.read(args.manifest))}))


if __name__ == '__main__':
    main()
