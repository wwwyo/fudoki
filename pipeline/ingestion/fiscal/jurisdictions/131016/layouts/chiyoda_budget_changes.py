"""Read the separate printed decompositions in Chiyoda amendments.

Candidates retain moku triples, left-page setsu deltas and explanation deltas.
Equal amounts do not establish project/setsu correspondence or approval.
The origin registry supplies identity; this reader has no separate source list.
"""
from __future__ import annotations

from importlib import import_module as _ingestion_module

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

import duckdb

from ingestion.fiscal.management.source_registry import INVENTORY, load_registry
location = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').location
normalize = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').normalize
number = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').number
positioned_rows = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').positioned_rows
from ingestion.inputs import OBJECTS, digest, encode, record_input
from ingestion.lib.pdf import pages_of
from ingestion.paths import REPO

NAMESPACE = 'chiyoda-supplementary-native'
CANDIDATE_NAMESPACE = NAMESPACE + '-candidate'
PROVIDER = 'ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes'
TABLE_ID = 'separate-printed-decompositions'
COLUMNS = {
    'source_row': 'BIGINT', 'record_kind': 'VARCHAR', 'code': 'VARCHAR',
    'label': 'VARCHAR', 'amount_before': 'BIGINT', 'amount_delta': 'BIGINT',
    'amount_after': 'BIGINT', 'physical_page': 'INTEGER', 'bbox_json': 'VARCHAR',
    'printed_text': 'VARCHAR', 'words_json': 'VARCHAR', 'context_json': 'VARCHAR',
}


def registered_specs() -> list[dict]:
    """Read enabled original and approval declarations from the single registry."""
    result = []
    for source in load_registry(INVENTORY)['sources']:
        if source['jurisdiction'] != '131016':
            continue
        for ingestion in source.get('ingestions', []):
            if ingestion['section'] != 'native_supplementary_detail' or not ingestion['enabled']:
                continue
            index = ingestion.get('profile', {}).get('edition_index')
            edition = source['editions'][index] if index is not None else edition_of(source)
            result.append(dict(source=source, edition=edition,
                approval=ingestion['options'].get('approval'),
                table=dict(table_id=table_id(source, edition))))
    return result


def registered_sources():
    from ingestion.fiscal.management.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    return {s['id']: Source(key=s['id'], catalog=None, jurisdiction_code=s['jurisdiction'],
        jurisdiction_name=jurisdiction_name(s['jurisdiction']), fiscal_year=s['fiscal_year'],
        fiscal_year_label=None, document_kind='supplementary', document_label=s['document_title'],
        dataset_title=None, encoding='', redistribute='review',
        redistribute_basis='当該PDFの再配布条件は未確認。別の資料の条件を適用しない。',
        license_id='NOASSERTION', attribution='千代田区', landing_page=s['landing_url'],
        raw_form='extracted', resources=tuple(Resource(direction='expenditure',
            resource_name=s['document_title']+' '+spec['edition']['account_label'], url=s['download_url'],
            url_basis='区の公式予算ページが補正号付きPDFを掲載。', table_id=spec['table']['table_id'])
            for spec in specs))
        for specs in grouped.values() for s in [specs[0]['source']]}


def edition_of(source: dict, account_label: str | None = None) -> dict:
    editions = [e for e in source['editions']
                if e['document_phase'] == 'supplementary'
                and e['in_scope']['status'] == 'included'
                and (account_label is None or e['account_label'] == account_label)]
    if len(editions) != 1:
        raise ValueError('Select one declared account edition from this original')
    edition = editions[0]
    if (edition['fiscal_year'] != source['fiscal_year']
        or edition['account_label'] not in source['account_labels']
        or edition['amendment_number'] not in source['amendment_numbers']):
        raise ValueError('Account edition differs from its containing original')
    return edition


def table_id(source: dict, edition: dict) -> str:
    return TABLE_ID if edition['account_label'] == '一般会計' else (
        TABLE_ID + '-edition-' + str(source['editions'].index(edition)))


def input_path(source: dict, namespace: str = NAMESPACE, *, edition: dict | None = None) -> str:
    edition = edition or edition_of(source)
    return (f'{namespace}/jurisdiction={source["jurisdiction"]}/year={source["fiscal_year"]}/'
            f'document_kind=supplementary/edition={source["content_inspection"]["sha256"]}/'
            f'direction=expenditure/table={table_id(source, edition)}')


def approval_evidence_objects(entries, *, namespace=NAMESPACE):
    """Derive council object references from the fixed input declarations."""
    refs = {}
    for entry in entries:
        if not entry['path'].startswith(namespace + '/'):
            continue
        approval = entry['source'].get('approval_proof')
        for evidence in (approval['evidence'].values() if approval else []):
            if (not re.fullmatch(r'[a-f0-9]{64}', evidence['sha256'])
                or type(evidence['bytes']) is not int or evidence['bytes'] <= 0):
                raise ValueError('Invalid council original hash or size')
            ref = dict(sha256=evidence['sha256'], bytes=evidence['bytes'],
                       key='inputs/origin/sha256/' + evidence['sha256'])
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting council original identity')
            refs[ref['key']] = ref
    return list(refs.values())


def restore_approval_evidence(entries, objects_dir: Path, *, remote=False, namespace=NAMESPACE):
    """Restore the council originals pinned by adopted approval declarations."""
    from ingestion.inputs import remote_object, verify_object
    for ref in approval_evidence_objects(entries, namespace=namespace):
        path = objects_dir / ref['key']
        if not path.exists() and remote:
            remote_object(ref, 'get', objects_dir=objects_dir)
        verify_object(ref, path.read_bytes())


def register_declarations(rows, history, entries, lock_path):
    """Bind adopted mixed observations and financial changes to the current registry."""
    from ingestion.inputs import source_metadata
    restore_approval_evidence(entries, OBJECTS)
    specs = {(spec['source']['id'], spec['table']['table_id']): spec for spec in registered_specs()}
    seen = set()
    for entry in entries:
        if not entry['path'].startswith(NAMESPACE + '/'):
            continue
        metadata = source_metadata(lock_path, entry)
        spec = specs[(metadata['source_key'], metadata['table_id'])]
        source, approval, edition = spec['source'], spec['approval'], spec['edition']
        table = spec['table']['table_id']
        approved = approval is not None
        sha = source['content_inspection']['sha256']
        for relative, ref in metadata['definition_files'].items():
            content = (REPO / relative).read_bytes()
            if ref != dict(sha256=digest(content), bytes=len(content)):
                raise ValueError('Chiyoda supplementary definition differs: ' + relative)
        if (entry['path'] != input_path(source, edition=edition) or entry['path'] in seen
            or entry['originEdition'] != sha or entry['jurisdiction'] != source['jurisdiction']
            or entry['fiscalYear'] != source['fiscal_year'] or entry['documentKind'] != 'supplementary'
            or entry['direction'] != 'expenditure'
            or entry['origin']['object']['bytes'] != source['content_inspection']['bytes']
            or metadata['namespace'] != NAMESPACE or metadata['table_id'] != table
            or metadata['request_url'] != source['download_url']
            or metadata['pages'] != [1, source['content_inspection']['pages']]
            or metadata['fund_label'] != edition['account_label']
            or metadata['amendment_number'] != edition['amendment_number']
            or metadata['approval_status'] != ('approved' if approved else 'unconfirmed')
            or metadata['approval_date'] != (approval['date'] if approved else None)
            or metadata['approval_proof'] != approval
            or metadata['phases'] != (['adjusted'] if approved else [])
            or metadata['canonical_changes'] is not approved
            or metadata['nonadditive'] is not True
            or metadata['project_setsu_linkage'] != 'unconfirmed'
            or metadata['source_amount_unit'] != '千円' or metadata['unit_multiplier'] != 1000):
            raise ValueError('Chiyoda adopted scope/approval differs from the origin registry')
        seen.add(entry['path'])
        structure = dict(hierarchy=['kan', 'kou', 'moku', 'project'], dimensions=[],
            funds=[dict(code='', label=metadata['fund_label'])], scope=dict(
                granularity=metadata['grain'], nonadditive=True,
                sourceAmountUnit='千円', unitMultiplier=1000, projectSetsuLinkage='unconfirmed',
                initialState='unconfirmed', authoritativeSupplementaryChanges=approved))
        declaration = dict(namespace=NAMESPACE, provider=PROVIDER, sourceKey=source['id'],
            documentKind='supplementary', documentLabel=source['document_title'],
            landingPage=source['landing_url'], url=source['download_url'], sha256=sha,
            licenseId='NOASSERTION', attribution='千代田区', redistributionStatus='unconfirmed',
            rawForm='extracted', tableId=table, fundLabel=metadata['fund_label'],
            pages=metadata['pages'], rawRowCount=metadata['rows'], rawSchema=metadata['raw_schema'],
            rawTableSha256=entry['table']['sha256'], rawTableBytes=entry['table']['bytes'],
            sourceAmountUnit='千円', unitMultiplier=1000, nonadditive=True,
            phases=metadata['phases'], canonicalChanges=approved,
            approvalStatus=metadata['approval_status'], approvalDate=metadata['approval_date'],
            approvalProof=approval, amendmentNumber=metadata['amendment_number'],
            projectSetsuLinkage='unconfirmed', phaseSemantics=metadata['phase_semantics'],
            grain=metadata['grain'], structure=structure)
        row = dict(dataset_id=':'.join([source['jurisdiction'], str(source['fiscal_year']),
            'expenditure', 'supplementary', sha, table]), jurisdiction_code=source['jurisdiction'],
            fiscal_year=source['fiscal_year'], direction='expenditure', document_kind='supplementary',
            source_json=json.dumps(declaration, ensure_ascii=False, sort_keys=True))
        rows.append(row)
        effective_at = metadata['approval_date'] if approval and approval.get('kind', 'budget_bill') == 'budget_bill' else None
        history.append(dict(**row, origin_sha256=sha, effective_at=effective_at,
            amendment_number=metadata['amendment_number'], fund_label=metadata['fund_label'],
            line_count=metadata['rows'], structure_json=json.dumps(structure, ensure_ascii=False)))
    expected = {input_path(spec['source'], edition=spec['edition']) for spec in specs.values()}
    if seen and seen != expected:
        raise ValueError('Chiyoda adopted table set differs from its enabled declarations')
    return rows, history


def extract(pdf: Path, source: dict, *, account_label: str | None = None) -> tuple[list[dict], dict]:
    """Require the observed edition and reconcile each decomposition separately."""
    inspected = source['content_inspection']
    if digest(pdf.read_bytes()) != inspected['sha256']:
        raise ValueError('Original differs from the inspected edition')
    pages = pages_of(pdf, 1, inspected['pages'])
    if len(pages) != inspected['pages']:
        raise ValueError('Original page count differs')
    texts = subprocess.run(['pdftotext', '-layout', str(pdf), '-'],
        capture_output=True, check=True).stdout.decode('utf-8').split('\f')
    if texts[-1].strip() == '':
        texts.pop()
    if len(texts) != len(pages):
        raise ValueError('Text and positioned PDF page counts differ')
    normalized_pages = [normalize(text) for text in texts]
    normalized_lines = [[normalize(line) for line in text.splitlines()] for text in texts]
    edition = edition_of(source, account_label)
    issue, account = edition['amendment_number'], edition['account_label']
    year = f'令和{edition["fiscal_year"] - 2018}年度'
    title = f'{account}補正予算第{issue}号'
    if year not in normalized_pages[0] or title not in normalized_pages[0]:
        raise ValueError('Cover year, account or amendment number differs')
    articles = [text for text in normalized_pages
                if year + '千代田区' + title in text and '第1条' in text]
    if len(articles) != 1:
        raise ValueError('Account has no unique first-article page')
    delta = re.search(r'歳入歳出それぞれ([\d,]+)千円を(追加|減額)', articles[0])
    if not delta:
        raise ValueError('First-article signed delta absent')
    total_delta = number(delta[1]) * (-1 if delta[2] == '減額' else 1)
    covers = [(pno, e) for pno, lines in enumerate(normalized_lines, 1)
              for e in source['editions']
              if f'{e["account_label"]}補正予算第{e["amendment_number"]}号説明書' in lines]
    selected = [pno for pno, e in covers if e == edition]
    if len(selected) != 1:
        raise ValueError('Account has no unique explanation cover')
    first = selected[0]
    last = min((pno - 1 for pno, _ in covers if pno > first), default=len(pages))
    records = []
    kan = kou = moku = project = setsu = None
    active = False
    money_edges = None
    moku_name_x = None
    moku_ids = set()
    left_page = None
    left_blocks = []

    def emit(kind, code, label, row, words, before=None, change=None, after=None):
        loc = location(row, words)
        record = dict(source_row=len(records)+1, record_kind=kind, code=code,
            label=label, amount_before=before, amount_delta=change, amount_after=after,
            physical_page=row['page'], bbox_json=json.dumps(loc['bbox']),
            printed_text=loc['printed_text'], words_json=json.dumps(words, ensure_ascii=False),
            context_json=None)
        record['_context'] = dict(kan=kan, kou=kou,
            moku=None if kind == 'section_total' else moku,
            project=None if kind == 'section_total' else project)
        records.append(record)
        return record

    for pno, page in enumerate(pages, 1):
        if not first < pno <= last:
            continue
        normalized = normalized_pages[pno-1]
        if '3歳出' in normalized_lines[pno-1]:
            active = True
        if active and ('第2債務負担' in normalized or '給与費明細書' in normalized):
            active = False
        if not active:
            continue
        explanation = '説明' in normalize(''.join(w[4] for w in page[2] if w[1] < 120))
        if explanation:
            if left_page != pno - 1 or not left_blocks:
                raise ValueError('Explanation has no adjacent expenditure table')
        else:
            left_page, left_blocks = pno, []
            if moku is not None:
                left_blocks.append((0, dict(kan=kan, kou=kou, moku=moku)))
        for row in positioned_rows(page, pno):
            words = row['words']
            whole = normalize(row['text'])
            if row['y'] > 770:
                continue
            if explanation:
                preceding = [context for y, context in left_blocks if y <= row['y'] + 1]
                if not preceding:
                    continue
                context = preceding[-1]
                if moku is not context['moku']:
                    project = None
                kan, kou, moku = context['kan'], context['kou'], context['moku']
                if not words or normalize(words[-1][4]) != '千円':
                    continue
                monetary = [w for w in words[:-1] if number(w[4]) is not None]
                if not monetary or words[-2] != monetary[-1]:
                    raise ValueError('Explanation amount is not adjacent to its currency')
                amount = monetary[-1]
                name_words = words[:words.index(amount)]
                name = normalize(''.join(w[4] for w in name_words))
                head = re.fullmatch(r'(\d+)(\D.*)', name)
                detail = re.fullmatch(r'\((\d+)\)(.+)', name)
                if head:
                    project = dict(code=head[1], label=head[2], row=len(records)+1)
                    emit('project_delta', head[1], head[2], row, words, change=number(amount[4]))
                elif detail and project is not None:
                    emit('detail_delta', detail[1], detail[2], row, words, change=number(amount[4]))
                else:
                    raise ValueError('Unsupported numbered explanation amount')
                continue
            heading = re.fullmatch(r'\(款\)(\d+)(.+)', whole)
            if heading:
                kan, kou = [heading[1], heading[2]], None
                continue
            heading = re.fullmatch(r'\(項\)(\d+)(.+)', whole)
            if heading:
                kou = [heading[1], heading[2]]
                money_edges = None
                continue
            currencies = [w for w in words if normalize(w[4]) == '千円']
            if len(currencies) == 6:
                money_edges = [w[2] for w in currencies]
                continue
            if not money_edges:
                continue
            amounts = []
            for edge in money_edges[:3]:
                found = [w for w in words if abs(w[2]-edge) < 1 and number(w[4]) is not None]
                if len(found) > 1:
                    raise ValueError('Multiple numbers in one amount column')
                amounts.append(found[0] if found else None)
            if all(w is not None for w in amounts):
                before, change, after = [number(w[4]) for w in amounts]
                if before + change != after:
                    raise ValueError('Printed moku/section before + delta differs from after')
                names = [w for w in words if w[2] < amounts[0][0]]
                name = normalize(''.join(w[4] for w in names))
                if name == '計':
                    emit('section_total', None, name, row, words,
                        before=before, change=change, after=after)
                else:
                    head = re.fullmatch(r'(\d+)(\D.*)', name)
                    if not head or not kan or not kou:
                        raise ValueError('Unsupported moku triple or missing hierarchy')
                    identity = (kan[0], kou[0], head[1])
                    if identity in moku_ids:
                        raise ValueError('Repeated moku triple needs an explicit continuation rule')
                    moku_ids.add(identity)
                    moku = dict(code=head[1], label=head[2], row=len(records)+1)
                    left_blocks.append((row['y'], dict(kan=kan, kou=kou, moku=moku)))
                    project = setsu = None
                    moku_name_x = names[1][0] if len(names) > 1 else None
                    emit('moku_control', head[1], head[2], row, words,
                        before=before, change=change, after=after)
            elif moku_name_x is not None:
                name_words = [w for w in words if moku_name_x-1 < w[0] < 130]
                if name_words and abs(name_words[0][0]-moku_name_x) < 1:
                    more = normalize(''.join(w[4] for w in name_words))
                    moku['label'] += more
                    control = records[moku['row']-1]
                    control['label'] = moku['label']
                    control['words_json'] = json.dumps(json.loads(control['words_json'])+name_words,
                        ensure_ascii=False)
                    control['printed_text'] += '\n'+' '.join(w[4] for w in name_words)
                    box = json.loads(control['bbox_json'])
                    box[3] = max(box[3], max(w[3] for w in name_words))
                    control['bbox_json'] = json.dumps(box)
            # Left setsu name is a separate cell, with its own aligned amount.
            setsu_words = [w for w in words if money_edges[4] < w[0] < money_edges[5]]
            if not setsu_words or moku is None:
                continue
            amount = next((w for w in setsu_words
                if abs(w[2]-money_edges[5]) < 1 and number(w[4]) is not None), None)
            name_words = [w for w in setsu_words if w is not amount]
            name = normalize(''.join(w[4] for w in name_words))
            head = re.fullmatch(r'(\d+)(\D.*)', name)
            if head and amount:
                setsu = emit('setsu_delta', head[1], head[2], row, setsu_words,
                    change=number(amount[4]))
            elif name and setsu is not None and amount is None:
                setsu['label'] += name
                # Keep all name fragments and their physical positions.
                setsu['words_json'] = json.dumps(json.loads(setsu['words_json']) + name_words,
                    ensure_ascii=False)
                setsu['printed_text'] += '\n' + ' '.join(w[4] for w in name_words)
                box = json.loads(setsu['bbox_json'])
                loc = location(row, name_words)['bbox']
                setsu['bbox_json'] = json.dumps([min(box[0],loc[0]),min(box[1],loc[1]),
                    max(box[2],loc[2]),max(box[3],loc[3])])
    controls = [r for r in records if r['record_kind'] == 'moku_control']
    if not controls or sum(r['amount_delta'] for r in controls) != total_delta:
        raise ValueError('Moku deltas do not equal the independent first-article delta')
    decomposition = defaultdict(lambda: defaultdict(int))
    for r in records:
        c = r['_context']
        if r['record_kind'] in ('setsu_delta','project_delta'):
            decomposition[c['moku']['row']][r['record_kind']] += r['amount_delta']
    exceptions = []
    for r in controls:
        for kind in ('setsu_delta','project_delta'):
            if kind not in decomposition[r['source_row']]:
                exceptions.append(dict(moku_source_row=r['source_row'], kind=kind,
                    reason='No printed monetary rows in this decomposition', amount_delta=r['amount_delta']))
                if r['amount_delta'] != 0:
                    raise ValueError('Changed moku lacks a printed decomposition')
            elif decomposition[r['source_row']][kind] != r['amount_delta']:
                raise ValueError('Independent decomposition differs from moku delta')
    for r in records:
        r['context_json'] = json.dumps(r.pop('_context'), ensure_ascii=False, sort_keys=True)
    counts = Counter(r['record_kind'] for r in records)
    return records, dict(source_id=source['id'], first_article_delta=total_delta,
        record_counts={kind:counts[kind] for kind in sorted(counts)},
        decomposition_exceptions=exceptions, project_setsu_linkage='unconfirmed',
        approval_status='unconfirmed', phase_semantics='signed amendment deltas; not adjusted totals')


def main(argv=None, *, raw_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id')
    parser.add_argument('--account-label')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--registered', action='store_true')
    parser.add_argument('--acquire-registered', action='store_true')
    args = parser.parse_args(argv)
    if args.acquire_registered:
        return acquire_registered()
    if not args.source_id or args.output_dir is None:
        parser.error('--source-id and --output-dir are required')
    source = next((s for s in load_registry(INVENTORY)['sources'] if s['id']==args.source_id), None)
    if (not source or source['jurisdiction']!='131016'
        or source['document_phase']!='supplementary' or source['format']!='pdf'):
        parser.error('This reader requires an inspected Chiyoda supplementary PDF')
    edition = edition_of(source, args.account_label)
    selected_table = table_id(source, edition)
    original = OBJECTS / f'inputs/origin/sha256/{source["content_inspection"]["sha256"]}'
    records, report = extract(original, source, account_label=edition['account_label'])
    spec = next((s for s in registered_specs()
                 if s['source']['id'] == source['id'] and s['edition'] == edition), None)
    if args.registered and spec is None:
        parser.error('Original has no enabled native supplementary declaration')
    namespace = NAMESPACE if args.registered else CANDIDATE_NAMESPACE
    out = raw_root / input_path(source, namespace, edition=edition) if raw_root is not None else args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute('create table candidate ('+', '.join(f'{k} {v}' for k,v in COLUMNS.items())+')')
        con.executemany('insert into candidate values ('+','.join('?' for _ in COLUMNS)+')',
            [[r[k] for k in COLUMNS] for r in records])
        con.execute('copy candidate to ? (format parquet)', [str(out/'data.parquet')])
    definition_paths = [Path(__file__).resolve(),
        REPO/'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_budget_detail.py',
        REPO/'pipeline/ingestion/fiscal/management/source_registry.py',
        REPO/'pipeline/ingestion/fiscal/management/sources.schema.json',
        REPO/'pipeline/ingestion/lib/pdf.py', REPO/'pipeline/ingestion/inputs.py',
        REPO/'pipeline/ingestion/paths.py']
    if args.registered:
        definition_paths += [INVENTORY, REPO/'pipeline/ingestion/fiscal/management/sources.py',
            REPO/'pipeline/ingestion/declarations.py', REPO/'pipeline/ingestion/acquire.py',
            REPO/'pipeline/ingestion/fiscal/jurisdictions/131016/layouts/chiyoda_supplementary_native_coverage.py',
            REPO/'pipeline/ingestion/fiscal/management/canonical_sources.py',
            REPO/'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_initial_native_coverage.py',
            REPO/'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/native_settlement_coverage.py',
            REPO/'pipeline/ingestion/fiscal/jurisdictions/132071/layouts/settlement2019_coverage.py',
            REPO/'pipeline/dbt/models/staging/fiscal/_chiyoda_supplementary_native_sources.yml',
            REPO/'pipeline/dbt/models/staging/fiscal/stg_131016__supplementary_native.sql',
            REPO/'pipeline/dbt/models/intermediate/fiscal/records/int_131016__supplementary_native.sql',
            REPO/'pipeline/dbt/models/intermediate/fiscal/records/int_131016__supplementary_native_datasets.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_131016_supplementary_native_observations.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_131016_supplementary_native_items.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_131016_supplementary_native_changes.sql',
            REPO/'pipeline/dbt/models/marts/csv/csv_131016_supplementary_native_observations.sql',
            REPO/'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_datasets.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_items.sql',
            REPO/'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_changes.sql', REPO/'uv.lock']
    metadata = dict(source_key=source['id'], namespace=namespace, request_url=source['download_url'],
        jurisdiction_code=source['jurisdiction'], fiscal_year=source['fiscal_year'], direction='expenditure',
        document_kind='supplementary', table_id=selected_table,
        fund_label=edition['account_label'], amendment_number=edition['amendment_number'],
        sha256=source['content_inspection']['sha256'], raw_form='extracted',
        source_amount_unit='千円', unit_multiplier=1000, project_setsu_linkage='unconfirmed',
        approval_status='unconfirmed', approval_date=None, approval_proof=None,
        phases=[], canonical_changes=False, nonadditive=True,
        grain='separate moku triples, moku-setsu deltas and project/detail deltas',
        phase_semantics=report['phase_semantics'], pages=[1,source['content_inspection']['pages']],
        definition_files={str(p.relative_to(REPO)):dict(sha256=digest(p.read_bytes()),bytes=p.stat().st_size)
            for p in definition_paths})
    if args.registered:
        approval = spec['approval']
        approved = approval is not None
        metadata.update(approval_status='approved' if approved else 'unconfirmed',
            approval_date=approval['date'] if approved else None, approval_proof=approval,
            phases=['adjusted'] if approved else [], canonical_changes=approved)
        report.update(approval_status=metadata['approval_status'],
                      approval_assigned_from_registry=True, phases=metadata['phases'])
    record_input(out, metadata, logical_path=input_path(source, namespace, edition=edition))
    # Inspection output is regenerated alongside the candidates, outside the registry.
    (out/'inspection.json').write_bytes(encode(report))
    print(json.dumps(report, ensure_ascii=False))


def acquire_registered():
    """Fetch declared originals through the shared cache and emit acquisition tables."""
    from ingestion.lib.http import http_get
    from ingestion.inputs import save_object
    from ingestion.paths import RAW
    fetched = set()
    for spec in registered_specs():
        source = spec['source']
        if source['id'] not in fetched:
            body = http_get(source['download_url']).body
            inspected = source['content_inspection']
            if digest(body) != inspected['sha256'] or len(body) != inspected['bytes']:
                raise ValueError('Budget original differs from the inspected edition')
            save_object('origin', body)
            fetched.add(source['id'])
        if spec['approval']:
            for url, evidence in spec['approval']['evidence'].items():
                body = http_get(url).body
                if digest(body) != evidence['sha256'] or len(body) != evidence['bytes']:
                    raise ValueError('Council original differs from the declared approval evidence')
                save_object('origin', body)
        main(['--source-id', source['id'], '--account-label', spec['edition']['account_label'],
              '--output-dir', str(RAW.parent/'reports'/source['id']),
              '--registered'], raw_root=RAW)


if __name__ == '__main__':
    main()
