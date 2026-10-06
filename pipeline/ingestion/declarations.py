"""採用した原典・表の識別子で、dbtへ取得元の宣言を渡す。"""
import json
from ingestion.fiscal.sources import all_sources
from ingestion.inputs import read_lock, source_metadata_bytes
from ingestion.paths import INPUT_LOCK


def declarations():
    sources = list(all_sources().values())
    rows = []
    history = []
    entries = read_lock(INPUT_LOCK)['entries']
    metadata = {entry['path']: json.loads(source_metadata_bytes(INPUT_LOCK, entry)) for entry in entries}
    adopted_detail_editions = set()
    for entry in entries:
        prov = metadata[entry['path']]
        if prov.get('table_id') == 'supplementary-expenditure-project-setsu':
            adopted_detail_editions.add((entry['jurisdiction'], entry['fiscalYear'],
                                        prov['fund_label'], prov['amendment_number']))
    for entry in entries:
        if entry['direction'] is None:
            continue
        prov = metadata[entry['path']]
        # partitionの表をIDの正本にする。legacy statementは無指定のIDを維持する。
        is_statement = 'extract_statement' in (prov.get('extractor') or '')
        table = (next((part.split('=', 1)[1] for part in entry['path'].split('/') if part.startswith('table=')), None)
                 if is_statement else prov.get('table_id'))
        is_observation = prov.get('observation_role') == 'independent-moku-setsu'
        is_supplementary_detail = table == 'supplementary-expenditure-project-setsu'
        is_settlement_pdf = (prov.get('source_key') or '').startswith('settlement-pdf:')
        if table and table != 'expenditure-detail' and not is_statement and not is_supplementary_detail and not is_settlement_pdf:
            continue
        dataset_id = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), entry['direction'],
                               entry['documentKind'], entry['originEdition'], *([table] if table else [])])
        matches = [source for source in sources if source.jurisdiction_code == entry['jurisdiction']
                   and source.fiscal_year == entry['fiscalYear'] and source.document_kind == entry['documentKind']
                   and (not prov.get('source_key') or source.key == prov['source_key'])
                   and any(r.direction == entry['direction']
                           and (r.url is None or r.url == prov['request_url'])
                           and (r.table_id == table if is_statement or r.table_id else True)
                           for r in source.resources)]
        if len(matches) != 1:
            raise ValueError(f'Adopted dataset has {len(matches)} source declarations: {dataset_id}')
        source = matches[0]
        superseded_pilot = table == 'expenditure-detail' and entry['documentKind'] == 'supplementary' and (
            entry['jurisdiction'], entry['fiscalYear'], prov.get('fund_label', '一般会計'),
            prov['amendment_number']) in adopted_detail_editions
        role = ('nonadditive-supplementary-reference' if superseded_pilot else prov.get('observation_role'))
        row = dict(dataset_id=dataset_id, jurisdiction_code=source.jurisdiction_code,
                   fiscal_year=source.fiscal_year, direction=entry['direction'], document_kind=source.document_kind,
                   source_json=json.dumps(dict(documentKind=source.document_kind, documentLabel=source.document_label,
                       landingPage=source.landing_page, url=prov['request_url'], sha256=prov['sha256'],
                       licenseId=source.license_id, attribution=source.attribution, rawForm=source.raw_form,
                       tableId=table, pages=prov.get('pages'),
                       observationRole=role, grain=prov.get('grain'),
                       explanationDatasetId=prov.get('explanation_dataset_id'),
                       **(dict(recognitionStatus=prov['recognition_status'], recognitionBasis=prov['recognition_basis'])
                          if is_settlement_pdf and 'recognition_status' in prov else {}),
                       **(dict(sourceAmountUnit=prov['source_amount_unit'], unitMultiplier=prov['unit_multiplier'],

                           rawTableSha256=entry['table']['sha256'], additiveWithinOwnGrain=role in ('legal-setsu', 'project-funding'),
                           independentBreakdown=True, yearBasis=prov['year_basis'], fundLabel=prov['fund_label'])
                          if is_settlement_pdf else {}),
                       **(dict(approvalDate=prov['effective_at'], approvalStatus=prov['approval_status'],
                           amendmentNumber=prov['amendment_number'], fundLabel=prov['fund_label'],
                           sourceAmountUnit='千円',
                            rawTableSha256=entry['table']['sha256'],
                           reserveExceptionRows=prov['extraction_evidence']['reserve_exception_rows'],
                           canonicalChanges=True) if is_supplementary_detail else
                          dict(canonicalChanges=False) if superseded_pilot else {})),
                       ensure_ascii=False, sort_keys=True))
        rows.append(row)
        if is_supplementary_detail:
            history.append(dict(**row, origin_sha256=entry['originEdition'],
                effective_at=prov['effective_at'], amendment_number=prov['amendment_number'],
                fund_label=prov['fund_label'], line_count=prov['rows'],
                structure_json=json.dumps(dict(hierarchy=['kan','kou','moku','project','setsu'], dimensions=['department'],
                    funds=[dict(code='',label=prov['fund_label'])],scope=dict(granularity=prov['grain'],
                    authoritativeSupplementaryChanges=True, initialState='unconfirmed',
                    sourceAmountUnit='千円', reserveExceptionRows=prov['extraction_evidence']['reserve_exception_rows'],
                    expenditureSetsuStatus='printed-code-name-and-active-master-required')),
                    ensure_ascii=False,sort_keys=True)))
        elif table and not is_statement and not is_observation and not is_settlement_pdf:
            history.append(dict(**row, origin_sha256=entry['originEdition'],
                effective_at=prov.get('effective_at'), amendment_number=prov['amendment_number'], line_count=prov['rows'],
                structure_json=json.dumps(dict(hierarchy=['kan','kou','moku'], dimensions=[],
                   funds=[dict(code='1', label='一般会計')], scope=dict(targets=['7-1-2','13-1-1'], granularity='moku',
                   expenditureSetsuStatus='unconfirmed')), ensure_ascii=False,sort_keys=True)))
    from ingestion.fiscal.initial_detail_provider import register_initial_declarations
    from ingestion.fiscal.council_approved_provider import register_council_declarations
    rows, history = register_council_declarations(rows, history, entries)
    from ingestion.fiscal.native_council_provider import register_native_council_declarations
    rows, history = register_native_council_declarations(rows, history, entries)
    from ingestion.fiscal.held5_council_provider import register_held5_council_declarations
    rows, history = register_held5_council_declarations(rows, history, entries)
    rows, history = register_initial_declarations(rows, history, entries)
    from ingestion.fiscal.tama_native_settlement.registration import register_native_settlement_declarations
    rows, history = register_native_settlement_declarations(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.chiyoda2025_native.registration import register_native_budget_declarations
    rows, history = register_native_budget_declarations(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.chiyoda2021_settlement_native.registration import register_native_settlement2021_declarations
    rows, history = register_native_settlement2021_declarations(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.akishima_initial445_registry import register_initial445_declarations
    rows, history = register_initial445_declarations(rows, history, entries)
    from ingestion.fiscal.akishima_settlement2024_registry import register_settlement2024_declarations
    rows, history = register_settlement2024_declarations(rows, history, entries)
    from ingestion.fiscal.akishima_settlement2020_2023_registry import register_settlement2020_2023_declarations
    rows, history = register_settlement2020_2023_declarations(rows, history, entries)
    from ingestion.fiscal.akishima_supplementary_fy2025_01_registry import register_supplementary_fy2025_01_declarations
    rows, history = register_supplementary_fy2025_01_declarations(rows, history, entries)
    from ingestion.fiscal.tama_pre2020.registration import register_pre2020_declarations
    rows, history = register_pre2020_declarations(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.akishima_settlement2019_registry import register_settlement2019_declarations
    rows, history = register_settlement2019_declarations(rows, history, entries)
    from ingestion.fiscal.komae_recovered_provider import register_komae_recovered_declarations
    rows, history = register_komae_recovered_declarations(rows, history, entries)
    from ingestion.fiscal.mitaka_initial2026.registration import register_declarations as register_mitaka
    rows, history = register_mitaka(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.tama_ordinary_history.registration import register_ordinary_history_declarations
    rows, history = register_ordinary_history_declarations(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.komae_supplementary_2020_1_provider import register_declarations as register_supplementary1
    rows, history = register_supplementary1(rows, history, entries, INPUT_LOCK)
    from ingestion.fiscal.tama_budget_detail import register_declarations as register_native_initial
    rows, history = register_native_initial(rows, history, entries, INPUT_LOCK)
    return rows, history


if __name__ == '__main__':
    rows, history = declarations()
    print(json.dumps(dict(sources=rows, history=history), ensure_ascii=False,sort_keys=True))
