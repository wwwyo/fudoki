"""Mitaka independent printed supplementary grains; sources.json owns registration."""
from __future__ import annotations

from importlib import import_module as _ingestion_module
from collections import defaultdict
import json
from pathlib import Path
from ingestion.fiscal.management.source_registry import INVENTORY, load_registry
from ingestion.fiscal.management.canonical_sources import report as canonical_report
from ingestion.inputs import OBJECTS, digest, encode, read_lock, record_input, source_metadata
from ingestion.paths import REPO
NAMESPACE = 'mitaka-supplementary-native'
PROVIDER = 'ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry'
ROLES = ('project_observations', 'project_delta', 'left_setsu_observations', 'left_setsu_delta')
COLUMNS = dict(
    source_row='BIGINT',
    source_observation_row='BIGINT',
    record_kind='VARCHAR',
    code='VARCHAR',
    label='VARCHAR',
    amount='BIGINT',
    amount_text='VARCHAR',
    physical_page='INTEGER',
    bbox_json='VARCHAR',
    printed_text='VARCHAR',
    words_json='VARCHAR',
    context_json='VARCHAR',
    source_grain='VARCHAR',
    printed_setsu_code='VARCHAR',
)
DEFINITION_PATHS = (
    'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_budget_changes.py',
    'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_supplementary_registry.py',
    'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_supplementary_native_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_budget_detail.py',
    'pipeline/ingestion/lib/pdf.py',
    'pipeline/ingestion/fiscal/management/canonical_sources.py',
    'pipeline/ingestion/fiscal/management/source_registry.py',
    'pipeline/ingestion/fiscal/management/sources.schema.json',
    'pipeline/ingestion/fiscal/management/sources.json',
    'pipeline/ingestion/fiscal/management/sources.py',
    'pipeline/ingestion/declarations.py',
    'pipeline/ingestion/acquire.py',
    'pipeline/ingestion/inputs.py',
    'pipeline/ingestion/paths.py',
    'pipeline/ingestion/fiscal/management/coverage_audit.py',
    'pipeline/ingestion/fiscal/jurisdictions/131016/layouts/chiyoda_budget_changes.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/native_settlement_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132071/layouts/settlement2019_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_initial_native_coverage.py',
    'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_changes.sql',
    'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_items.sql',
    'pipeline/dbt/macros/fiscal_budget_items.sql',
    'packages/fiscal/setsu-master.ts',
    'pipeline/declarations.ts',
    'uv.lock',
    'pipeline/dbt/models/staging/fiscal/stg_132047__supplementary_native.sql',
    'pipeline/dbt/models/intermediate/fiscal/records/int_132047__supplementary_native.sql',
    'pipeline/dbt/models/intermediate/fiscal/records/int_132047__supplementary_native_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_132047_supplementary_native_changes.sql',
    'pipeline/dbt/models/marts/records/fiscal_132047_supplementary_native_items.sql',
    'pipeline/dbt/models/marts/records/fiscal_132047_supplementary_native_left_setsu.sql',
    'pipeline/dbt/models/marts/records/fiscal_132047_supplementary_native_left_setsu_observations.sql',
    'pipeline/dbt/models/marts/records/fiscal_132047_supplementary_native_observations.sql',
    'pipeline/dbt/models/marts/csv/csv_132047_supplementary_native_left_setsu.sql',
    'pipeline/dbt/models/marts/csv/csv_132047_supplementary_native_left_setsu_observations.sql',
    'pipeline/dbt/models/marts/csv/csv_132047_supplementary_native_observations.sql',
    'pipeline/dbt/models/staging/fiscal/_mitaka_supplementary_native_sources.yml',
)

def definition_files():
    return {
        p: {'sha256': digest((REPO / p).read_bytes()), 'bytes': (REPO / p).stat().st_size}
        for p in DEFINITION_PATHS
    }

def identity(source, edition):
    return (
        source['jurisdiction'],
        edition['fiscal_year'],
        edition['account_label'],
        'supplementary',
        edition['amendment_number'],
    )

def selection_state(inventory=None):
    inventory = inventory or load_registry(INVENTORY)
    state = canonical_report(inventory, read_lock(INVENTORY.parent.parent / 'sources.lock.json'))
    groups = {
        (g['jurisdiction'], g['fiscal_year'], g['account_label'], g['document_phase'], g['amendment_number']): g
        for g in state['groups']
    }
    pending = set()
    for s in state['content_unconfirmed_sources']:
        for e in s['identified_scopes']:
            pending.add(
                (
                    s['jurisdiction'],
                    e['fiscal_year'],
                    e['account_label'],
                    e['document_phase'],
                    e['amendment_number'],
                ),
            )
    return (groups, pending)

def make_spec(source, edition_index, pages, approval):
    edition = source['editions'][edition_index]
    first, last = pages
    if (
        source['jurisdiction'] != '132047'
        or edition['document_phase'] != 'supplementary'
        or first > last
        or (last - first + 1) % 2
        or last > source['content_inspection']['pages']
    ):
        raise ValueError('Mitaka registered native facing-book scope differs')
    if approval is None:
        raise ValueError('Mitaka canonical scope requires explicit approval evidence')
    return {
        'source': source,
        'edition': edition,
        'edition_index': edition_index,
        'approval': approval,
        'tables': [
            {
                'table_id': f"supplementary-{edition['amendment_number']}-pages-{first}-{last}-{role}",
                'observation_role': role,
                'pages': pages,
                'account': edition['account_label'],
                'edition_index': edition_index,
            }
            for role in ROLES
        ],
    }

def registered_specs():
    inventory = load_registry(INVENTORY)
    groups, pending = selection_state(inventory)
    specs = []
    seen = set()
    for source in inventory['sources']:
        if source['jurisdiction'] != '132047':
            continue
        for ingestion in source.get('ingestions', []):
            if ingestion['section'] != 'native_supplementary_detail' or not ingestion['enabled']:
                continue
            edition_index = ingestion['profile']['edition_index']
            edition = source['editions'][edition_index]
            key = identity(source, edition)
            group = groups.get(key)
            if (
                key in pending
                or group is None
                or group['canonical_source_id'] != source['id']
                or group['selection_status'] in ('revision_order_unconfirmed', 'complementary_parts_unconfirmed')
            ):
                raise ValueError('Mitaka scope selection or identified pending original remains unresolved')
            if key in seen:
                raise ValueError('Mitaka repeated canonical supplementary scope')
            seen.add(key)
            specs.append(
                make_spec(
                    source,
                    edition_index,
                    ingestion['profile']['physical_pages'],
                    ingestion['options'].get('approval'),
                ),
            )
    return specs

def input_path(source, table):
    return f"{NAMESPACE}/jurisdiction=132047/year={source['editions'][table.get('edition_index', 0)]['fiscal_year']}/document_kind=supplementary/edition={source['content_inspection']['sha256']}/direction=expenditure/table={table['table_id']}"

def fields(spec, table, definitions):
    source = spec['source']
    edition = spec['edition']
    approval = spec['approval']
    role = table['observation_role']
    canonical = role == 'project_delta'
    effective = None
    return dict(
        namespace=NAMESPACE,
        source_key=source['id'],
        jurisdiction_code='132047',
        fiscal_year=edition['fiscal_year'],
        document_kind='supplementary',
        direction='expenditure',
        origin_sha256=source['content_inspection']['sha256'],
        request_url=source['download_url'],
        final_url=source['content_inspection']['final_url'],
        landing_page=source['landing_url'],
        document_title=source['document_title'],
        account=edition['account_label'],
        fund_label=edition['account_label'],
        amendment_number=edition['amendment_number'],
        table_id=table['table_id'],
        pages=table['pages'],
        source_amount_unit='千円',
        unit_multiplier=1000,
        source_amount_kind='supplementary',
        observation_role=role,
        nonadditive=role != 'project_delta',
        phases=[],
        financial_phase=None,
        canonical_changes=canonical,
        approval_status='approved',
        approval_date=approval['date'],
        approval_proof=approval,
        effective_at=effective,
        baseline_status='unconfirmed',
        phase_semantics='signed supplementary event delta; not adjusted total',
        project_setsu_linkage='independent_breakdowns',
        grain=(
            'project-or-explicit-reserve-moku'
            if role.startswith('project')
            else 'independent-moku-setsu'
        ),
        extractor='ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes',
        definition_files=definitions,
    )

def emit_registered(output, original, spec, master_path=None, definitions=None, raw_root=None, master_body=None):
    extract = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes').extract
    extract_left = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes').extract_left
    write_table = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes').write_table
    rows, leaves, checks, pages = extract(original, spec['edition'])
    if pages != spec['tables'][0]['pages']:
        raise ValueError('Mitaka discovered pages differ from registered physical range')
    body = (
        master_body
        if master_body is not None
        else (Path(master_path).read_bytes() if master_path is not None else master_catalog_body())
    )
    master = json.loads(body)
    left, roots, leftchecks = extract_left(rows, original, spec['edition'], pages, master, digest(body))
    roles = dict(zip(ROLES, (rows, leaves, left, roots)))
    definitions = definitions or definition_files()
    entries = []
    for table in spec['tables']:
        table['edition_index'] = spec['edition_index']
        dest = (
            Path(raw_root) / input_path(spec['source'], table)
            if raw_root is not None
            else Path(output) / table['observation_role']
        )
        data = roles[table['observation_role']]
        write_table(
            dest,
            data,
            financial=table['observation_role'] in ('project_delta', 'left_setsu_delta'),
        )
        metadata = fields(spec, table, definitions)
        metadata.update(
            first_article_evidence={'page': checks['printed_article_page'], 'amount_delta': checks['printed_article_delta']},
            printed_total=checks['printed_article_delta'],
        )
        entry = record_input(dest, metadata, logical_path=input_path(spec['source'], table))
        entries.append(entry)
    result = {
        'source_id': spec['source']['id'],
        'edition_index': spec['edition_index'],
        'pages': pages,
        'checks': checks,
        'left_checks': leftchecks,
        'candidate_inputs': entries,
        'installed': False,
    }
    (Path(output) / 'inspection.json').write_bytes(encode(result))
    return result

def registered_sources():
    from ingestion.fiscal.management.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    return {
        sid: Source(
            key=sid,
            catalog=None,
            jurisdiction_code='132047',
            jurisdiction_name=jurisdiction_name('132047'),
            fiscal_year=specs[0]['source']['fiscal_year'],
            fiscal_year_label=None,
            document_kind='supplementary',
            document_label=specs[0]['source']['document_title'],
            dataset_title=None,
            encoding='',
            redistribute='review',
            redistribute_basis='当該原典の再配布条件は未確認。',
            license_id='NOASSERTION',
            attribution='三鷹市',
            landing_page=specs[0]['source']['landing_url'],
            raw_form='extracted',
            resources=tuple(
                (
                    Resource(
                        direction='expenditure',
                        resource_name=t['account'] + ' ' + t['observation_role'],
                        url=specs[0]['source']['download_url'],
                        url_basis='自治体の補正予算原典。',
                        table_id=t['table_id'],
                    )
                    for spec in specs
                    for t in spec['tables']
                ),
            ),
        )
        for (sid, specs) in grouped.items()
    }

def register_declarations(rows, history, entries, lock_path):
    specs = {(s['source']['id'], t['table_id']): (s, t) for s in registered_specs() for t in s['tables']}
    adopted = [e for e in entries if e['path'].startswith(NAMESPACE + '/')]
    if not adopted:
        return (rows, history)
    restore_approval_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes').restore_approval_evidence
    restore_approval_evidence(adopted, OBJECTS, namespace=NAMESPACE)
    definitions = definition_files()
    seen = set()
    for entry in adopted:
        raw = source_metadata(lock_path, entry)
        key = (raw['source_key'], raw['table_id'])
        if key not in specs or key in seen:
            raise ValueError('Mitaka adopted table repeated or undeclared')
        seen.add(key)
        spec, table = specs[key]
        table['edition_index'] = spec['edition_index']
        expected = fields(spec, table, definitions)
        source = spec['source']
        edition = spec['edition']
        origin_sha256 = source['content_inspection']['sha256']
        if (
            entry['path'] != input_path(source, table)
            or entry['originEdition'] != origin_sha256
            or entry['fiscalYear'] != edition['fiscal_year']
            or entry['jurisdiction'] != '132047'
            or entry['origin']['object']['bytes'] != source['content_inspection']['bytes']
            or raw['raw_schema'] != [dict(name=n, type=v) for n, v in COLUMNS.items()]
            or any((raw.get(k) != v for k, v in expected.items()))
        ):
            raise ValueError('Mitaka fixed input scope/approval/support differs from SSOT')
        structure = {
            'hierarchy': (
                ['kan', 'kou', 'moku', 'project']
                if table['observation_role'].startswith('project')
                else ['kan', 'kou', 'moku']
            ),
            'dimensions': [],
            'funds': [dict(code='', label=edition['account_label'])],
            'scope': {
                'granularity': expected['grain'],
                'nonadditive': expected['nonadditive'],
                'initialState': 'unconfirmed',
                'projectSetsuRelation': 'independent_breakdowns',
                'sourceAmountKind': 'supplementary',
            },
        }
        declaration = dict(
            namespace=NAMESPACE,
            provider=PROVIDER,
            sourceKey=source['id'],
            tableId=table['table_id'],
            sha256=origin_sha256,
            documentKind='supplementary',
            documentLabel=source['document_title'],
            landingPage=source['landing_url'],
            url=source['download_url'],
            fundLabel=edition['account_label'],
            pages=table['pages'],
            rawRowCount=raw['rows'],
            rawSchema=raw['raw_schema'],
            rawTableSha256=entry['table']['sha256'],
            rawTableBytes=entry['table']['bytes'],
            sourceAmountUnit='千円',
            unitMultiplier=1000,
            sourceAmountKind='supplementary',
            observationRole=table['observation_role'],
            nonadditive=expected['nonadditive'],
            canonicalChanges=expected['canonical_changes'],
            phases=[],
            financialPhase=None,
            approvalStatus='approved',
            approvalDate=expected['approval_date'],
            approvalProof=spec['approval'],
            effectiveAt=expected['effective_at'],
            amendmentNumber=edition['amendment_number'],
            phaseSemantics=expected['phase_semantics'],
            projectSetsuLinkage='independent_breakdowns',
            grain=expected['grain'],
            firstArticleEvidence=raw['first_article_evidence'],
            printedTotal=raw['printed_total'],
            structure=structure,
        )
        row = dict(
            dataset_id=f"132047:{edition['fiscal_year']}:expenditure:supplementary:{origin_sha256}:{table['table_id']}",
            jurisdiction_code='132047',
            fiscal_year=edition['fiscal_year'],
            direction='expenditure',
            document_kind='supplementary',
            source_json=json.dumps(declaration, ensure_ascii=False, sort_keys=True),
        )
        rows.append(row)
        history.append(
            dict(
                **row,
                origin_sha256=origin_sha256,
                effective_at=expected['effective_at'],
                amendment_number=edition['amendment_number'],
                fund_label=edition['account_label'],
                line_count=raw['rows'],
                structure_json=json.dumps(structure, ensure_ascii=False),
            ),
        )
    if seen != set(specs):
        raise ValueError('Mitaka adopted four-role tables do not match enabled scopes')
    return (rows, history)

def acquire_registered():
    """Acquire enabled SSOT scopes; publish no table unless all controls pass."""
    inspect_original = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes').inspect_original
    from ingestion.lib.http import http_get
    from ingestion.inputs import save_object
    from ingestion.paths import RAW
    restore_approval_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes').restore_approval_evidence
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    definitions = definition_files() if grouped else None
    master = master_catalog_body()
    fetched = set()
    for specs in grouped.values():
        source = specs[0]['source']
        expected = source['content_inspection']
        body = http_get(source['download_url']).body
        if digest(body) != expected['sha256'] or len(body) != expected['bytes']:
            raise ValueError('Mitaka acquired original differs from fixed inspected bytes')
        origin = save_object('origin', body)
        original = inspect_original(OBJECTS / origin['key'], source)
        for spec in specs:
            for url, evidence in spec['approval']['evidence'].items():
                if url in fetched:
                    continue
                body = http_get(url).body
                if digest(body) != evidence['sha256'] or len(body) != evidence['bytes']:
                    raise ValueError('Mitaka approval original differs from declared evidence')
                save_object('origin', body)
                fetched.add(url)
            output = RAW / NAMESPACE / 'inspection' / source['id'] / str(spec['edition_index'])
            emitted = emit_registered(output, original, spec, definitions=definitions, raw_root=RAW, master_body=master)
            restore_approval_evidence(emitted['candidate_inputs'], OBJECTS, namespace=NAMESPACE)
    return 0

def master_catalog_body():
    """Use the same authoritative catalog provider as pipeline/declarations.ts."""
    import subprocess
    return subprocess.check_output(
        [
            'bun',
            '-e',
            "import {expenditureSetsuMaster} from './packages/fiscal/setsu-master.ts';process.stdout.write(JSON.stringify(expenditureSetsuMaster()))",
        ],
        cwd=REPO,
    )

def main(argv=None):
    import argparse
    inspect_original = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_budget_changes').inspect_original
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--acquire-registered', action='store_true')
    ap.add_argument('--registered', action='store_true')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args(argv)
    if args.acquire_registered:
        if args.output or args.registered:
            ap.error('acquire flag cannot combine with candidate output')
        return acquire_registered()
    if not args.registered or args.output is None:
        ap.error('candidate generation requires --registered and --output')
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    definitions = definition_files()
    master = master_catalog_body()
    results = []
    for specs in grouped.values():
        source = specs[0]['source']
        original = inspect_original(OBJECTS / f"inputs/origin/sha256/{source['content_inspection']['sha256']}", source)
        for spec in specs:
            results.append(
                emit_registered(
                    args.output / source['id'] / str(spec['edition_index']),
                    original,
                    spec,
                    definitions=definitions,
                    master_body=master,
                ),
            )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'batch.json').write_bytes(
        encode(
            {
                'originals': len(grouped),
                'scopes': len(results),
                'results': results,
                'installed': False,
            },
        ),
    )
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
