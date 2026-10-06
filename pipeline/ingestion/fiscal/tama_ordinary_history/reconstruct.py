"""Reconstruct fixed recovered Tama FY2019/FY2020 ordinary-account partitions from immutable originals.

Reads original document bytes from the content-addressed input object cache
(default: ingestion.inputs.OBJECTS) and Git-declared evidence files beside this
module. Never touches the network, a mutable official URL, or any former
.agent recovery directory. Produces one raw partition per (original, table_id)
plus a whole-table readback for review.

Extraction rule (native text layer only, no OCR):
- word/page observations come from `pdftotext -bbox-layout` per page.
- project-rows anchors on the printed code pair `NN-NN-NN NNN-NNN` and reads
  the project name from its own column band (x0 in [100,176)), the department
  from [176,244), and the printed amount token from [232,268). Wrapped lines
  and bracketed continuations are preserved verbatim.
- printed_unit is taken only from the document's own `単位：…` header; numeric
  unit stays NULL when the page prints none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
from ingestion.fiscal.tama_ordinary_history.contracts import (
    bounded_read, evidence_metadata, runtime_executable, read_reviewed_definitions, verify_duck_runtime,
    resource_read, resource_pin, installed_root, PACKAGE, require, seal, validate_specs, bind_cli_definition_lock)

DIRECTORY = Path(__file__).absolute().parent
NAMESPACE = 'tama-ordinary-history'

CODE = re.compile(r'(\d{2})\s*-\s*(\d{2})\s*-\s*(\d{2})\s+(\d{3})\s*-\s*(\d{3})')
CODEWORD = re.compile(r'[\d\-]+')
MONEY = re.compile(r'[△−-]?\d[\d,]*')
FUNDING = ['国庫支出金', '都支出金', '地方債', 'その他特定財源', '一般財源']
UNIT_MARK = re.compile(r'単位：\s*([千億万]?円)')
NAME_X = (99.0, 176.0)
DEPT_X = (176.0, 244.0)
AMOUNT_X = (232.0, 268.0)
HEADER = {'事業名', '所属', '決算額', '財源内訳', '財源', '金額', '掲載頁', '事業概要', '款・項・目'}
EXPENDITURE_DOCS = {'4-1.pdf', '7-1.pdf', '13-1.pdf', '16-1.pdf'}
ORDINARY_DOCS = EXPENDITURE_DOCS | {'3-1.pdf', '6-1.pdf', '12-1.pdf', '15-1.pdf'}


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def origin_bytes(cache_dir: Path, sha: str, expected_bytes: int) -> bytes:
    expected = resource_pin({'sha256': sha, 'bytes': expected_bytes})
    # Cache originals are resources; transaction/artifact 20MB cap is inapplicable.
    return resource_read(cache_dir / 'inputs/origin/sha256' / sha, expected)



def parse_amount(s):
    if not s or not MONEY.fullmatch(s):
        return None
    return int(s.replace(',', '').replace('△', '-').replace('−', '-'))


def words_pages(pdf: Path,definitions):
    out = subprocess.run([runtime_executable(DIRECTORY, 'pdftotext',definitions), '-bbox-layout', str(pdf), '-'],
                         capture_output=True, check=True).stdout.decode()
    pages = []
    for m in re.finditer(r'<page[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"[^>]*>(.*?)</page>', out, re.S):
        ws = [tuple(map(float, w[:4])) + (w[4],)
              for w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<', m.group(3))]
        pages.append((float(m.group(1)), float(m.group(2)), ws))
    return pages


def text_lines(pdf: Path,definitions):
    out = subprocess.run([runtime_executable(DIRECTORY, 'pdftotext',definitions), '-layout', str(pdf), '-'],
                         capture_output=True, check=True).stdout.decode()
    return [p.split('\n') for p in out.split('\f')]


def printed_unit(lines_pages):
    for lines in lines_pages[:3]:
        for line in lines:
            m = UNIT_MARK.search(line)
            if m:
                return m.group(1)
    return None


def extract_rows(pages_words, lines_pages):
    rows = []
    ordinal = 0
    for pg, (pw, lines) in enumerate(zip(pages_words, lines_pages), start=1):
        anchors = [li for li, line in enumerate(lines) if CODE.search(line)]
        anchor_ys = []
        for li in anchors:
            m = CODE.search(lines[li])
            cand = [wy0 for x0, wy0, x1, wy1, t in pw
                    if 100 <= x0 < 136 and (t == m.group(4) or t == '-' + m.group(5))]
            by_y = sorted(set(cand))
            yok = [y for y in by_y
                   if any(t == m.group(4) for x0, wy0, x1, wy1, t in pw if wy0 == y and 100 <= x0 < 136)
                   and any(t == '-' + m.group(5) for x0, wy0, x1, wy1, t in pw if wy0 == y and 100 <= x0 < 136)]
            anchor_ys.append(min(yok) if yok else 10**9)
        for ai, li in enumerate(anchors):
            nj = anchors[ai + 1] if ai + 1 < len(anchors) else len(lines)
            block = lines[li:nj]
            m = CODE.search(block[0])
            if not m:
                continue
            ordinal += 1
            y0 = anchor_ys[ai] - 0.1
            y1 = (anchor_ys[ai + 1] - 0.1) if ai + 1 < len(anchors) else 10**9
            raw = '\n'.join(block)
            structural = lambda t: '款：' in t or '項：' in t or '目：' in t or MONEY.fullmatch(t) or CODEWORD.fullmatch(t)
            name_words, dept_words = [], []
            for x0, wy0, x1, wy1, t in sorted(pw, key=lambda w: (w[1], w[0])):
                if not (y0 <= wy0 < y1) or t in HEADER or structural(t):
                    continue
                if NAME_X[0] <= x0 < NAME_X[1]:
                    name_words.append(t)
                elif DEPT_X[0] <= x0 < DEPT_X[1]:
                    dept_words.append(t)
            raw_tok = None
            for x0, wy0, x1, wy1, t in sorted(pw, key=lambda w: (w[1], w[0])):
                if AMOUNT_X[0] <= x0 < AMOUNT_X[1] and y0 <= wy0 < y1 and MONEY.fullmatch(t):
                    raw_tok = t; break
            if raw_tok is None:
                for b in block:
                    mm = re.search(r'\s(\d[\d,]*)\s+都支出金', b)
                    if mm:
                        raw_tok = mm.group(1); break
            funding = {}
            for b in block:
                for k in FUNDING:
                    mm = re.search(re.escape(k) + r'\s+([△−-]?\d[\d,]*)', b)
                    if mm:
                        funding[k] = parse_amount(mm.group(1))
            rows.append(dict(source_ordinal=ordinal, physical_page=pg,
                             printed_kan=m.group(1), printed_kou=m.group(2), printed_moku=m.group(3),
                             printed_project_major=m.group(4), printed_project_minor=m.group(5),
                             printed_project_name=''.join(name_words) or None,
                             printed_department=''.join(dept_words) or None,
                             printed_amount_raw=raw_tok,
                             decided_amount=parse_amount(raw_tok) if raw_tok else None,
                             funding_national=funding.get('国庫支出金'),
                             funding_prefectural=funding.get('都支出金'),
                             funding_bonds=funding.get('地方債'),
                             funding_specific=funding.get('その他特定財源'),
                             funding_general=funding.get('一般財源'),
                             raw_block=raw))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--objects', type=Path, required=True,
                    help='content-addressed object store root (inputs/origin/sha256/...)')
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--input-lock',type=Path,required=True,help='parent sealed schema3 joint lock; no schema2 provenance overlay')
    ap.add_argument('--input-lock-sha',required=True)
    ap.add_argument('--input-lock-bytes',type=int,required=True)
    args = ap.parse_args()
    # Closure pins the declared installed replay bytes, not any CLI JSON body.
    definitions = read_reviewed_definitions(DIRECTORY)
    bind_cli_definition_lock(args.input_lock,dict(sha256=args.input_lock_sha,bytes=args.input_lock_bytes),definitions,DIRECTORY)
    verify_duck_runtime(DIRECTORY,duckdb,definitions)
    declared_path = installed_root(DIRECTORY) / PACKAGE / 'replay-manifest.json'
    declared = bounded_read(declared_path)
    expected = definitions[PACKAGE + '/replay-manifest.json']
    require(seal(declared) == expected, 'declared installed replay manifest changed')
    supplied = bounded_read(args.manifest)
    require(supplied == declared and seal(supplied) == expected, 'CLI replay manifest differs from installed declaration')
    manifest = json.loads(declared)
    evidence_metadata(manifest)  # exact20 original identities;15 adopted;5 replay-only
    sources_body = bounded_read(DIRECTORY / 'sources.toml')
    require(seal(sources_body) == definitions[PACKAGE + '/sources.toml'], 'declared source config changed')
    evidence_body = bounded_read(DIRECTORY / 'evidence-manifest.json')
    schema_body = bounded_read(DIRECTORY / 'raw-schema.json')
    require(seal(evidence_body) == definitions[PACKAGE + '/evidence-manifest.json']
            and seal(schema_body) == definitions[PACKAGE + '/raw-schema.json'], 'declared evidence/schema changed')
    validate_specs(tomllib.loads(sources_body.decode())['ordinary_history'],
                   json.loads(evidence_body), json.loads(schema_body), manifest)
    # Only now may extraction or serializer startup begin. No raw rule changed.
    con = duckdb.connect(config={"memory_limit":"256MB","threads":1,"max_temp_directory_size":"0B","temp_directory":""})
    errors = []
    produced = {}
    for item in manifest['inputs']:
        body = origin_bytes(args.objects, item['sha256'], item['bytes'])
        complete = body[:4] == b'%PDF' and b'%%EOF' in body[-2048:]
        if item.get('complete_capture') and not complete:
            errors.append(f"incomplete capture marked complete: {item['path']}")
            continue
        if not complete:
            produced[item['path']] = dict(status='fragment-preserved')
            continue
        rel = item['path']
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            tmp.write(body);tmp.flush()
            pdf = Path(tmp.name)
            pages = words_pages(pdf,definitions)
            tp = text_lines(pdf,definitions)
        unit = printed_unit(tp)
        dir_rows = extract_rows([ws for _, _, ws in pages], tp) if Path(rel).name in EXPENDITURE_DOCS else []
        got = digest(body)
        for o, (w, h, ws) in enumerate(pages, start=1):
            produced.setdefault('page_observations', []).append(dict(
                origin_sha256=got, document=rel, physical_page=o, width=w,
                height=h, word_count=len(ws)))
            for wo, (x0, y0, x1, y1, t) in enumerate(ws, start=1):
                produced.setdefault('word_observations', []).append(dict(
                    origin_sha256=got, document=rel, physical_page=o,
                    source_ordinal=wo, printed_word=t,
                    x_min=x0, y_min=y0, x_max=x1, y_max=y1))
        for r in dir_rows:
            r.update(origin_sha256=got, document=rel,
                     year=item['year'], account=item['account'],
                     direction=item['direction'],
                     printed_unit=unit,
                     source_unit_status='printed' if unit else 'unprinted',
                     complete_capture=True)
            produced.setdefault('project_rows', []).append(r)
    if errors:
        print('FAIL closed:', *errors, sep='\n  ')
        raise SystemExit(1)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in produced.items():
        if isinstance(rows, dict):
            continue
        with open(args.out / f'{name}.jsonl', 'w') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        select = f"select * from read_json_auto('{args.out}/{name}.jsonl')"
        if name == 'project_rows':
            cols = "source_ordinal,physical_page,printed_kan,printed_kou,printed_moku,printed_project_major,printed_project_minor,printed_project_name,printed_department,decided_amount,funding_national,funding_prefectural,funding_bonds,funding_specific,funding_general,raw_block,origin_sha256,document,year,account,direction,printed_unit,source_unit_status,printed_amount_raw,complete_capture"
            select = (f"select {cols}, cast(null as varchar) normalized_unit, cast(null as varchar) unit_judgment_evidence "
                      f"from read_json_auto('{args.out}/{name}.jsonl')")
        con.execute(f"copy ({select}) to '{args.out}/{name}.parquet' (format parquet)")
        (args.out / 'partitions').mkdir(exist_ok=True)
        docs = sorted({r.get('document') for r in rows})
        for d in docs:
            fn = f"{name}__{d.replace('/', '_').replace('.pdf', '')}.parquet"
            con.execute(f"copy ({select} where document='{d}') "
                        f"to '{args.out}/partitions/{fn}' (format parquet)")
        print(name, len(rows), 'partitions', len(docs))


if __name__ == '__main__':
    main()


def evidence_roles() -> dict:
    return evidence_metadata(json.loads(bounded_read(DIRECTORY / 'replay-manifest.json')))


def evidence_objects() -> list:
    # Object identity has exactly key/SHA/bytes. Scope roles stay separate.
    return [v['ref'] for v in evidence_roles().values()]


def restore_evidence(objects_dir: Path, *, remote: bool = False) -> int:
    from ingestion.inputs import remote_object, safe_relative, verify_object
    count = 0
    for ref in evidence_objects():
        cached = objects_dir / safe_relative(ref['key'])
        if not cached.exists():
            if not remote:
                raise FileNotFoundError('Ordinary-history replay original not cached: ' + ref['key'])
            remote_object(ref, 'get', objects_dir=objects_dir)
        verify_object(ref,resource_read(cached,{k:ref[k] for k in ('sha256','bytes')}))
        count += 1
    return count
