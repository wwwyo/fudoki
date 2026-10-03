"""採用した原典・表の識別子で、dbtへ取得元の宣言を渡す。"""
import json
from ingestion.fiscal.sources import all_sources
from ingestion.inputs import read_lock, provenance_bytes
from ingestion.paths import INPUT_LOCK


def declarations():
    sources = list(all_sources().values())
    rows = []
    history = []
    for entry in read_lock(INPUT_LOCK)['entries']:
        if entry['direction'] is None:
            continue
        prov = json.loads(provenance_bytes(INPUT_LOCK, entry))
        table = prov.get('table_id')
        if table and table != 'expenditure-detail':
            continue
        dataset_id = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), entry['direction'],
                               entry['documentKind'], entry['originEdition'], *([table] if table else [])])
        matches = [source for source in sources if source.jurisdiction_code == entry['jurisdiction']
                   and source.fiscal_year == entry['fiscalYear'] and source.document_kind == entry['documentKind']
                   and any(r.direction == entry['direction'] and (not table or r.url == prov['request_url']) for r in source.resources)]
        if len(matches) != 1:
            raise ValueError(f'Adopted dataset has {len(matches)} source declarations: {dataset_id}')
        source = matches[0]
        row = dict(dataset_id=dataset_id, jurisdiction_code=source.jurisdiction_code,
                   fiscal_year=source.fiscal_year, direction=entry['direction'], document_kind=source.document_kind,
                   source_json=json.dumps(dict(documentKind=source.document_kind, documentLabel=source.document_label,
                       landingPage=source.landing_page, url=prov['request_url'], sha256=prov['sha256'],
                       licenseId=source.license_id, attribution=source.attribution, rawForm=source.raw_form,
                       tableId=table, pages=prov.get('pages')), ensure_ascii=False, sort_keys=True))
        rows.append(row)
        if table:
            history.append(dict(**row, origin_sha256=entry['originEdition'],
                effective_at=prov.get('effective_at'), amendment_number=prov['amendment_number'], line_count=prov['rows'],
                structure_json=json.dumps(dict(hierarchy=['kan','kou','moku'], dimensions=[],
                   funds=[dict(code='1', label='一般会計')], scope=dict(targets=['7-1-2','13-1-1'], granularity='moku',
                   expenditureSetsuStatus='unconfirmed')), ensure_ascii=False,sort_keys=True)))
    return rows, history


if __name__ == '__main__':
    rows, history = declarations()
    print(json.dumps(dict(sources=rows, history=history), ensure_ascii=False,sort_keys=True))
