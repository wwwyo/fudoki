"""Read the separate printed decompositions in Chiyoda FY2026 amendments.

Candidates retain moku triples, left-page setsu deltas and explanation deltas.
Equal amounts do not establish project/setsu correspondence or approval.
The origin registry supplies identity; this reader has no separate source list.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

import duckdb

from ingestion.fiscal.source_registry import INVENTORY, load_registry
from ingestion.fiscal.tama_budget_detail import location, normalize, number, positioned_rows
from ingestion.inputs import OBJECTS, digest, encode, record_input
from ingestion.lib.pdf import pages_of
from ingestion.paths import REPO

NAMESPACE = 'chiyoda-supplementary-native-candidate'
COLUMNS = {
    'source_row': 'BIGINT', 'record_kind': 'VARCHAR', 'code': 'VARCHAR',
    'label': 'VARCHAR', 'amount_before': 'BIGINT', 'amount_delta': 'BIGINT',
    'amount_after': 'BIGINT', 'physical_page': 'INTEGER', 'bbox_json': 'VARCHAR',
    'printed_text': 'VARCHAR', 'words_json': 'VARCHAR', 'context_json': 'VARCHAR',
}


def extract(pdf: Path, source: dict) -> tuple[list[dict], dict]:
    """Require the observed edition and reconcile each decomposition separately."""
    inspected = source['content_inspection']
    if digest(pdf.read_bytes()) != inspected['sha256']:
        raise ValueError('Original differs from the inspected edition')
    pages = pages_of(pdf, 1, inspected['pages'])
    if len(pages) != inspected['pages']:
        raise ValueError('Original page count differs')
    texts = subprocess.run(['pdftotext', '-layout', str(pdf), '-'],
        capture_output=True, check=True).stdout.decode('utf-8').split('\f')
    issue = source['amendment_numbers'][0]
    if f'令和8年度一般会計補正予算第{issue}号千代田区' not in normalize(texts[0]):
        raise ValueError('Cover year, account or amendment number differs')
    article = normalize(''.join(texts[:4]))
    delta = re.search(r'歳入歳出それぞれ([\d,]+)千円を(追加|減額)', article)
    if not delta:
        raise ValueError('First-article signed delta absent')
    total_delta = number(delta[1]) * (-1 if delta[2] == '減額' else 1)
    records = []
    kan = kou = moku = project = setsu = None
    active = False
    money_edges = None
    moku_name_x = None
    moku_ids = set()

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
        normalized = normalize(texts[pno-1])
        if '3歳出' in normalized:
            active = True
        if active and ('第2債務負担' in normalized or '給与費明細書' in normalized):
            active = False
        if not active:
            continue
        explanation = '説明' in normalize(''.join(w[4] for w in page[2] if w[1] < 120))
        for row in positioned_rows(page, pno):
            words = row['words']
            whole = normalize(row['text'])
            if row['y'] > 770:
                continue
            if explanation:
                if moku is None:
                    raise ValueError('Explanation has no preceding moku')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    source = next((s for s in load_registry(INVENTORY)['sources'] if s['id']==args.source_id), None)
    if (not source or source['jurisdiction']!='131016' or source['fiscal_year']!=2026
        or source['document_phase']!='supplementary' or source['account_labels']!=['一般会計']
        or source['format']!='pdf' or len(source['amendment_numbers'])!=1
        or source['amendment_numbers'][0] not in (1,2,3)):
        parser.error('This reader supports registered Chiyoda FY2026 general-account amendments only')
    original = OBJECTS / f'inputs/origin/sha256/{source["content_inspection"]["sha256"]}'
    records, report = extract(original, source)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute('create table candidate ('+', '.join(f'{k} {v}' for k,v in COLUMNS.items())+')')
        con.executemany('insert into candidate values ('+','.join('?' for _ in COLUMNS)+')',
            [[r[k] for k in COLUMNS] for r in records])
        con.execute('copy candidate to ? (format parquet)', [str(out/'data.parquet')])
    definition_paths = [Path(__file__).resolve(),
        REPO/'pipeline/ingestion/fiscal/tama_budget_detail.py',
        REPO/'pipeline/ingestion/fiscal/source_registry.py',
        REPO/'pipeline/ingestion/fiscal/sources.schema.json',
        REPO/'pipeline/ingestion/lib/pdf.py', REPO/'pipeline/ingestion/inputs.py',
        REPO/'pipeline/ingestion/paths.py']
    metadata = dict(source_key=source['id'], namespace=NAMESPACE, request_url=source['download_url'],
        jurisdiction_code=source['jurisdiction'], fiscal_year=source['fiscal_year'], direction='expenditure',
        document_kind='supplementary', table_id='separate-printed-decompositions',
        fund_label='一般会計', amendment_number=source['amendment_numbers'][0],
        sha256=source['content_inspection']['sha256'], raw_form='extracted',
        source_amount_unit='千円', unit_multiplier=1000, project_setsu_linkage='unconfirmed',
        approval_status='unconfirmed', phases=[], canonical_changes=False, nonadditive=True,
        grain='separate moku triples, moku-setsu deltas and project/detail deltas',
        phase_semantics=report['phase_semantics'], pages=[1,source['content_inspection']['pages']],
        definition_files={str(p.relative_to(REPO)):dict(sha256=digest(p.read_bytes()),bytes=p.stat().st_size)
            for p in definition_paths})
    record_input(out, metadata, logical_path=f'{NAMESPACE}/jurisdiction=131016/year=2026/'
        f'document_kind=supplementary/edition={metadata["sha256"]}/direction=expenditure/table={metadata["table_id"]}')
    # Inspection output is regenerated alongside the candidates, outside the registry.
    (out/'inspection.json').write_bytes(encode(report))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
