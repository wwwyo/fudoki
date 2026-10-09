"""Read the two explicit replacements in the FY2023 No4 amendment motion."""
from __future__ import annotations

from importlib import import_module as _ingestion_module

import copy
import json
from pathlib import Path
import re
import subprocess

extract = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_changes').extract
inspect_original = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_changes').inspect_original
location = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').location
normalize = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').normalize
number = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').number
positioned_rows = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').positioned_rows
write_table = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').write_table
from ingestion.inputs import OBJECTS, digest
from ingestion.lib.pdf import pages_of


def cached_original(source: dict) -> Path:
    spec = source['content_inspection']
    path = OBJECTS / f'inputs/origin/sha256/{spec["sha256"]}'
    body = path.read_bytes()
    if digest(body) != spec['sha256'] or len(body) != spec['bytes']:
        raise ValueError('Amendment dependency original hash/bytes differ')
    return path


def _identity(text: str) -> tuple[str, str]:
    match = re.fullmatch(r'(\d+)(.+)', text)
    if match is None:
        raise ValueError('Motion has no explicit printed hierarchy code/name')
    return match[1], match[2]


def extract_motion(pdf: Path, spec: dict) -> tuple[list[dict], dict]:
    """Extract native motion rows and explicit roots; retain the replaced proposal."""
    source, proposal = spec['source'], spec['proposal']['source']
    edition = spec['proposal']['edition']
    if (proposal['jurisdiction'], edition['fiscal_year'], edition['account_label'],
            edition['amendment_number']) != ('132241', 2023, '一般会計', 4):
        raise ValueError('This reviewed motion layout only covers Tama FY2023 general No4')
    if pdf != cached_original(source):
        body = pdf.read_bytes()
        if digest(body) != source['content_inspection']['sha256'] or len(body) != source['content_inspection']['bytes']:
            raise ValueError('Motion original differs from its declaration')
    original = inspect_original(cached_original(proposal), proposal)
    _, leaves, checks, scope = extract(original, edition)
    if not checks['complete_observed_grain']:
        raise ValueError('Replaced proposal is not reconciled at its printed grain')
    pages = pages_of(pdf, 1, 3)
    text = normalize(subprocess.check_output(['pdftotext', '-layout', str(pdf), '-']).decode())
    if (f'第{scope["bill"]}号議案' not in text
        or '令和5年度多摩市一般会計補正予算(第4号)に対する修正動議' not in text
        or '第1条第2項第1表を次のとおり修正する。' not in text
        or '本年度予算額' not in text or '(単位:千円)' not in text):
        raise ValueError('Motion bill/event/replacement/column semantics differ')
    records = []
    for page, positioned in enumerate(pages, 1):
        for row in positioned_rows(positioned, page):
            records.append(dict(source_row=len(records)+1, record_kind='motion-original-row',
                code=None, label=None, amount=None, amount_text=None,
                kan=None, kou=None, moku=None, project=None, setsu=None, department=None,
                location=location(row, row['words']), composition=None))
    replacements = []
    for low, high in ((145, 215), (250, 285)):
        words = [w for w in pages[2][2] if low <= w[1] < high]
        def column(left, right):
            return sorted((w for w in words if left <= w[0] < right), key=lambda w: (w[1], w[0]))
        def printed(left, right):
            return normalize(''.join(w[4] for w in column(left, right)))
        kan, kou, moku = [_identity(printed(a, b)) for a, b in ((90, 150), (150, 220), (220, 290))]
        project = _identity(printed(670, 780))
        setsu = _identity(printed(395, 470)) if printed(395, 470) else None
        annual_old, annual_new, delta_old, delta_new = [column(a, b) for a, b in
            ((290, 345), (345, 395), (470, 520), (520, 570))]
        if any(len(cell) != 1 for cell in (annual_old, annual_new, delta_old, delta_new)):
            raise ValueError('Motion replacement operands are not unique printed cells')
        matching = [(n, r) for n, r in enumerate(leaves, 1)
            if tuple(r['moku']['key']) == (kan[0], kou[0], moku[0])
            and r['project']['code'] == project[0]
            and r.get('printed_setsu_code') == (setsu[0] if setsu else None)]
        if len(matching) != 1:
            raise ValueError('Motion does not identify exactly one original financial target')
        financial_row, old = matching[0]
        if (old['kan'][1], old['kou'][1], normalize(old['moku']['label']), normalize(old['project']['label'])) != (
                kan[1], kou[1], moku[1], project[1]):
            raise ValueError('Printed original/motion target names differ')
        if old['amount'] != number(delta_old[0][4]) or old['moku']['amount_after'] != number(annual_old[0][4]):
            raise ValueError('Motion original columns differ from the proposal operands')
        rec = copy.deepcopy(old)
        rec.update(source_row=len(records)+1, record_kind='motion-replacement',
            amount=number(delta_new[0][4]), amount_text=delta_new[0][4],
            location=location({'page': 3}, sorted(words, key=lambda w: (w[1], w[0]))), department=None)
        rec['project']['row'] = rec['source_row']
        if rec['setsu'] is not None:
            rec['setsu'].update(code=setsu[0], label=setsu[1], row=rec['source_row'])
        revision = rec['amount'] - old['amount']
        revised_moku_delta = old['moku']['amount_delta'] + revision
        rec['moku'].update(amount_delta=revised_moku_delta,
            amount_after=number(annual_new[0][4]), operand_words=None)
        if (rec['moku']['amount_before'] + revised_moku_delta != rec['moku']['amount_after']
            or number(annual_new[0][4])-number(annual_old[0][4]) != revision):
            raise ValueError('Revised annual moku amount is not before plus signed delta')
        rec['composition'] = dict(proposal_source_id=proposal['id'],
            proposal_origin_sha256=proposal['content_inspection']['sha256'],
            proposal_table_id=spec['proposal']['tables'][1]['table_id'],
            proposal_financial_row=financial_row, proposal_observation_row=old['source_row'],
            replaced_proposal=dict(amount=old['amount'], location=old['location'],
                context={k:old[k] for k in ('kan','kou','moku','project','setsu','department')}),
            printed_cells=dict(moku_original_annual=annual_old, moku_revised_annual=annual_new,
                original_delta=delta_old, revised_delta=delta_new),
            department_status='motion unprinted; NULL', funding_status='original proposal raw only',
            same_event_replacement=True)
        records.append(rec)
        replacements.append(rec)
    revision_net = sum(r['amount']-r['composition']['replaced_proposal']['amount'] for r in replacements)
    if len(records) != 55 or len(replacements) != 2 or revision_net != 0:
        raise ValueError('Reviewed motion row population or same-event revision net differs')
    return records, dict(observations=53, explicit_replacements=2, revision_net=revision_net,
        proposal_total=scope['printed_delta'], composed_total=scope['printed_delta']+revision_net,
        other_accounts_composed=False, adopted=False, phases=[])


def write_motion(directory: Path, records: list[dict]) -> None:
    """Preserve the raw14 schema, adding explicit dependency context to the JSON cell."""
    import duckdb
    write_table(directory, records, financial=False)
    with duckdb.connect(':memory:') as connection:
        connection.execute('create table enriched as select * from read_parquet(?)', [str(directory/'data.parquet')])
        for row in records:
            context = {k:row[k] for k in ('kan','kou','moku','project','setsu','department')}
            context['composition'] = row['composition']
            connection.execute('update enriched set context_json=? where source_row=?',
                [json.dumps(context, ensure_ascii=False), row['source_row']])
        connection.execute('copy enriched to ? (format parquet,compression zstd)', [str(directory/'data.parquet')])
