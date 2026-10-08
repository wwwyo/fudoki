"""Import adopted Parquet bytes into selected target/direction manifests."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path

from ingestion.fiscal import manifest
from ingestion.fiscal.run import table_receipt
from ingestion.fiscal.storage import fetch, save, cleanup
from ingestion.paths import PIPELINE


@lru_cache(maxsize=1)
def relocation_rules() -> tuple[re.Pattern, dict]:
    mapping = json.loads(Path(__file__).with_name('legacy').joinpath('relocations.json').read_text())
    replacements = {**mapping['files'], **mapping['modules']}
    for old, new in mapping['files'].items():
        # Only moved layout packages own directory aliases. Jurisdiction notes
        # move into separate folders; their common parent must stay unchanged.
        if (len(Path(old).parent.parts) > 3
                and str(Path(old).parent) != 'pipeline/ingestion/fiscal/jurisdictions'):
            replacements[str(Path(old).parent)] = str(Path(new).parent)
    pattern = re.compile('(?:' + '|'.join(re.escape(old) for old in sorted(replacements, key=len, reverse=True))
                         + r')(?![A-Za-z0-9_])')
    return pattern, replacements


def relocated_declaration(value: object) -> object:
    """Move code references, preserving all fiscal values and original identities."""
    pattern, replacements = relocation_rules()
    def transform(item):
        if isinstance(item, dict):
            return {transform(key): transform(child) for key, child in item.items()}
        if isinstance(item, list):
            return [transform(child) for child in item]
        if isinstance(item, str):
            return pattern.sub(lambda match: replacements[match[0]], item)
        return item
    return transform(value)


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


def distinct_table_id(entry: dict, scopes: list[dict], conversions: list[dict]) -> str | None:
    """Keep assigned IDs, separating only explicitly different single accounts."""
    ident = table_id(entry, scopes)
    owners = {conversion['id']: conversion for conversion in conversions}
    if ident not in owners:
        return ident
    accounts = {scope['account'] for scope in scopes}
    previous = {scope['account'] for original in owners[ident]['inputs'] for scope in original['scope']}
    if (len(accounts) != 1 or len(previous) != 1 or accounts == previous
            or entry['source'].get('fund_label') not in accounts):
        return None
    suffix = hashlib.sha256(manifest.canonical(sorted(accounts))).hexdigest()[:16]
    scoped = ident + '-' + suffix
    return scoped if len(scoped) <= 96 and scoped not in owners else None


def plan(lock: dict) -> tuple[list[dict], dict]:
    index = selected_sources()
    documents = {}
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
                    'direction': entry['direction'], 'candidate_id': selection['selected_candidate_id'],
                    'status': 'planned', 'conversions': [], 'tables': []})
        ident = distinct_table_id(entry, scopes, document['conversions'])
        if ident is None:
            held.append({'path': entry['path'], 'reason': 'ambiguous_stable_table_identity'})
            continue
        document['conversions'].append({'id': ident, 'converter': 'fiscal/layouts/retained/convert.py',
            'options_schema': 'fiscal/layouts/retained/options.schema.json', 'dependencies': [],
            'inputs': [{'sha256': entry['originEdition'], 'format': file['format'], 'scope': scopes}],
            'options': {'objects': [{'table_id': ident, **entry['table']}]},
            'expected_tables': [{'table_id': ident, 'legacy_path': entry['path'],
                                 'declaration': relocated_declaration(entry['source'])}]})
    result = sorted(documents.values(), key=lambda d: str(manifest.manifest_path(d['target'], d['direction'])))
    for document in result:
        manifest.validate(document)
        for conversion in document['conversions']:
            manifest.resolved_inputs(document, conversion)
    return result, {'legacy_entries': len(lock['entries']), 'manifests': len(result),
                    'planned_tables': sum(len(d['conversions']) for d in result),
                    'held': held, 'held_by_reason': dict(Counter(item['reason'] for item in held))}


def import_tables(document: dict, *, remote: bool, origin_sizes: dict[str, int], extend_plans: bool = False) -> dict:
    path = manifest.manifest_path(document['target'], document['direction'])
    if path.exists():
        existing = manifest.read(path)
        if existing['status'] == 'ready' and existing['conversions'] == document['conversions']:
            manifest.require_current(existing)
            return {'status': 'already_saved', 'tables': len(existing['tables'])}
        if existing['conversions'] != document['conversions']:
            planned = {conversion['id']: conversion for conversion in document['conversions']}
            if not extend_plans or not all(planned.get(conversion['id']) == conversion
                                           for conversion in existing['conversions']):
                raise ValueError('Existing manifest differs from migration plan; do not replace it implicitly')
    before = manifest.fingerprints(document)
    prepared = []
    for conversion in document['conversions']:
        for reference in conversion['options']['objects']:
            source = fetch(reference, remote=remote)
            table = table_receipt(document, conversion, reference['table_id'], source,
                                  input_fingerprint=before[conversion['id']],
                                  origins=[{'sha256': item['sha256'], 'bytes': origin_sizes[item['sha256']]}
                                           for item in conversion['inputs']])
            prepared.append((table, source))
    result = deepcopy(document)
    result.update(status='ready', tables=[item[0] for item in prepared])
    manifest.validate(result)
    if before != manifest.fingerprints(document):
        raise ValueError('Input conditions changed during table import')
    for table, source in prepared:
        save(result, table, source, remote=remote)
    manifest.require_current(result)
    manifest.write(path, result)
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
    origin_sizes = {}
    for entry in lock['entries']:
        sha, size = entry['originEdition'], entry['origin']['object']['bytes']
        if sha in origin_sizes and origin_sizes[sha] != size:
            raise ValueError('Conflicting legacy original byte sizes')
        origin_sizes[sha] = size
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    saved = 0
    for document in documents:
        path = manifest.manifest_path(document['target'], document['direction'])
        if args.write_plans and not path.exists():
            manifest.write(path, document)
        if args.remote:
            result = import_tables(document, remote=True, origin_sizes=origin_sizes, extend_plans=args.extend_plans)
            saved += result['tables']
            print(json.dumps({'manifest': str(path.relative_to(PIPELINE)), **result}), flush=True)
    print(json.dumps({key: value for key, value in report.items() if key != 'held'} | {'saved_tables': saved}))


if __name__ == '__main__':
    main()
