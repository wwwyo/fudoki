"""Import adopted Parquet bytes into selected target/direction manifests."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ingestion.fiscal import manifest
from ingestion.fiscal.run import inspect_table, table_receipt
from ingestion.fiscal.storage import fetch, save, cleanup, verify
from ingestion.paths import PIPELINE


def selected_sources() -> dict[str, list[dict]]:
    index = defaultdict(list)
    for path in sorted((PIPELINE / 'source_selection').glob('*.json')):
        for selection in json.loads(path.read_text())['selections']:
            if not selection.get('archive'):
                continue
            candidate = next(item for item in selection['candidates'] if item['id'] == selection['selected_candidate_id'])
            for file in candidate['files']:
                index[file['sha256']].append({'selection': selection, 'file': file})
    return index


def table_id(entry: dict, scopes: list[dict]) -> str:
    parts = [part for part in entry['path'].split('/')
             if not part.startswith(('jurisdiction=', 'year=', 'document_kind=', 'edition=', 'direction='))]
    role = '/'.join(parts) or 'csv'
    # Old CSV identities were edition-only, even for separate general/special files.
    # Import this explicit selected scope once; the resulting table ID is persisted.
    if not parts:
        accounts = {scope['account'] for scope in scopes}
        role += ('-general' if accounts == {'一般会計'} else
                 '-special' if '一般会計' not in accounts else '-combined')
    prefix = parts[0] if parts and '=' not in parts[0] else 'raw'
    prefix = ''.join(char if char.isascii() and (char.isalnum() or char in '-_') else '-' for char in prefix.lower())[:48]
    return prefix + '-' + hashlib.sha256(role.encode()).hexdigest()[:16]


def distinct_table_id(entry: dict, scopes: list[dict], owners: dict[str, set[str]]) -> str | None:
    """Keep assigned IDs, separating only explicitly different single accounts."""
    ident = table_id(entry, scopes)
    if ident not in owners:
        return ident
    accounts = {scope['account'] for scope in scopes}
    previous = owners[ident]
    if (len(accounts) != 1 or len(previous) != 1 or accounts == previous
            or entry['source'].get('fund_label') not in accounts):
        return None
    suffix = hashlib.sha256(manifest.canonical(sorted(accounts))).hexdigest()[:16]
    scoped = ident + '-' + suffix
    return scoped if len(scoped) <= 96 and scoped not in owners else None


def plan(lock: dict) -> tuple[list[dict], dict]:
    index = selected_sources()
    documents = {}
    bindings = {}
    assigned = defaultdict(dict)
    held = []
    for entry in lock['entries']:
        if entry['direction'] not in ('expenditure', 'revenue'):
            held.append({'path': entry['path'], 'reason': 'support_or_direction_unconfirmed'})
            continue
        kind = 'initial' if entry['documentKind'] == 'budget' else entry['documentKind']
        number = entry['source'].get('amendment_number')
        matches = [item for item in index[entry['originEdition']]
                   if item['selection']['target']['jurisdiction'] == entry['jurisdiction']
                   and item['selection']['target']['fiscal_year'] == entry['fiscalYear']
                   and item['selection']['target']['document_kind'] == kind
                   and (kind != 'supplementary' or item['selection']['target'].get('amendment_number') == number)]
        if len(matches) != 1:
            held.append({'path': entry['path'], 'reason': 'selected_origin_or_target_unconfirmed'})
            continue
        item = matches[0]
        selection, file = item['selection'], item['file']
        scopes = [{key: value for key, value in scope.items() if key != 'direction'}
                  for scope in file['scope'] if scope['direction'] == entry['direction']]
        for scope in scopes:
            if 'pages' in scope:
                scope['pages'] = [[r['start'], r['end']] for r in scope['pages']]
        if not scopes:
            held.append({'path': entry['path'], 'reason': 'selected_direction_unconfirmed'})
            continue
        target = selection['target']
        key = tuple([json.dumps(target, sort_keys=True), entry['direction']])
        document = documents.setdefault(key, {'schema_version': 1, 'target': target,
                    'direction': entry['direction'], 'conversions': [], 'tables': []})
        ident = distinct_table_id(entry, scopes, assigned[key])
        if ident is None:
            held.append({'path': entry['path'], 'reason': 'ambiguous_stable_table_identity'})
            continue
        document['conversions'].append({'id': ident, 'converter': 'fiscal/layouts/retained/convert.py',
            'inputs': [{'sha256': entry['originEdition']}],
            'options': {'objects': [{'table_id': ident, **entry['table']}]},
            'expected_tables': [{'table_id': ident}]})
        assigned[key][ident] = {scope['account'] for scope in scopes}
        binding = bindings.setdefault(key, {'schema_version': 1, 'target': target,
                                           'direction': entry['direction'], 'tables': []})
        binding['tables'].append({'table_id': ident, 'raw_path': entry['path'] + '/data.parquet'})
    result = sorted(documents.values(), key=lambda d: str(manifest.manifest_path(d['target'], d['direction'])))
    for document in result:
        manifest.validate(document)
        for conversion in document['conversions']:
            manifest.resolved_inputs(document, conversion)
    return result, {'legacy_entries': len(lock['entries']), 'manifests': len(result),
                    'planned_tables': sum(len(d['conversions']) for d in result),
                    'held': held, 'held_by_reason': dict(Counter(item['reason'] for item in held)),
                    'dbt_bindings': list(bindings.values())}


def import_tables(document: dict, *, remote: bool, extend_plans: bool = False,
                  bindings: dict | None = None) -> dict:
    from dbt_inputs import check_write, path_for, write as write_bindings
    path = manifest.manifest_path(document['target'], document['direction'])
    original_bytes = path.read_bytes() if path.exists() else None
    binding_path = path_for(document)
    binding_bytes = binding_path.read_bytes() if binding_path.exists() else None
    if bindings is not None:
        check_write(bindings, document, extend=extend_plans)
    retained = []
    if original_bytes is not None:
        existing = manifest.validate(json.loads(original_bytes), path=path)
        if existing['tables'] and existing['conversions'] == document['conversions']:
            manifest.require_current(existing)
            if bindings is not None:
                write_bindings(bindings, existing, extend=extend_plans)
            return {'status': 'already_saved', 'tables': len(existing['tables'])}
        if existing['conversions'] != document['conversions']:
            planned = {conversion['id']: conversion for conversion in document['conversions']}
            if not extend_plans or not all(planned.get(conversion['id']) == conversion
                                           for conversion in existing['conversions']):
                raise ValueError('Existing manifest differs from migration plan; do not replace it implicitly')
        if existing['tables']:
            manifest.require_current(existing)
            retained = deepcopy(existing['tables'])
    before = manifest.fingerprints(document)
    retained_ids = {table['table_id'] for table in retained}
    for table in retained:
        source = fetch(table['object'], remote=remote)
        verify(source, table['object'])
        if inspect_table(source, table.get('metadata')) != table['row_count']:
            raise ValueError('Retained table row count differs from its receipt')
    prepared = []
    for conversion in document['conversions']:
        for reference in conversion['options']['objects']:
            if reference['table_id'] in retained_ids:
                continue
            source = fetch(reference, remote=remote)
            table = table_receipt(document, conversion, reference['table_id'], source,
                                  input_fingerprint=before[conversion['id']])
            prepared.append((table, source))
    result = deepcopy(document)
    receipts = {table['table_id']: table for table in retained + [item[0] for item in prepared]}
    result['tables'] = [receipts[expected['table_id']] for conversion in document['conversions']
                        for expected in conversion['expected_tables']]
    manifest.validate(result)
    if before != manifest.fingerprints(document):
        raise ValueError('Input conditions changed during table import')
    for table, source in prepared:
        save(result, table, source, remote=remote)
    manifest.require_current(result)
    if ((path.read_bytes() if path.exists() else None) != original_bytes
            or bindings is not None and (binding_path.read_bytes() if binding_path.exists() else None) != binding_bytes):
        raise ValueError('Registrations changed during table import; do not overwrite them')
    manifest.write(path, result)
    try:
        if bindings is not None:
            write_bindings(bindings, result, extend=extend_plans)
    except Exception:
        # Restore only our registration if binding publication fails; preserve concurrent edits.
        if manifest.read(path) == result:
            if original_bytes is None:
                path.unlink()
            else:
                manifest.write(path, json.loads(original_bytes))
        raise
    cleanup(result)
    return {'status': 'saved', 'tables': len(result['tables'])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--write-plans', action='store_true')
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--extend-plans', action='store_true',
                        help='Allow additional tables; existing conversion definitions must remain identical')
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    documents, report = plan(lock)
    from dbt_inputs import path_for, write as write_bindings
    bindings = {path_for(binding): binding for binding in report['dbt_bindings']}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    saved = 0
    for document in documents:
        path = manifest.manifest_path(document['target'], document['direction'])
        binding = bindings[path_for(document)]
        if args.remote:
            result = import_tables(document, remote=True, extend_plans=args.extend_plans, bindings=binding)
            saved += result['tables']
            print(json.dumps({'manifest': str(path.relative_to(PIPELINE)), **result}), flush=True)
        elif args.write_plans:
            if path.exists() and manifest.read(path)['conversions'] != document['conversions']:
                raise ValueError('Existing manifest differs; import additional tables with --remote before extending bindings')
            from dbt_inputs import check_write
            check_write(binding, document, extend=args.extend_plans)
            if not path.exists():
                manifest.write(path, document)
            write_bindings(binding, document, extend=args.extend_plans)
    print(json.dumps({key: value for key, value in report.items() if key not in ('held', 'dbt_bindings')}
                     | {'saved_tables': saved, 'dbt_binding_manifests': len(bindings)}))


if __name__ == '__main__':
    main()
