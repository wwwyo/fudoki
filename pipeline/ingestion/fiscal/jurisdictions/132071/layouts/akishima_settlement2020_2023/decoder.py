"""Finite FY2020-2023 Akishima settlement native-cell decoder; no OCR, network, allocation or name matching.

Coordinates are measured from the actual originals. Portrait years (2020, 2021)
print each spread as two physical pages (budget/hierarchy page, then executed
page). Landscape years (2022, 2023) print the same spread as a single physical
page whose right half equals the portrait right page translated +595.4pt.
"""
from __future__ import annotations
import re, html, json, hashlib
from collections import defaultdict

MONEY = re.compile(r'^(?:△|-)?[\d,]+$')
OFF = 595.4  # landscape right-half translation, measured from the originals

# Left-half column right-edges (portrait pt): budget money then setsu budget.
L_MONEY = [176.9, 237.7, 298.6, 359.5, 420.4]
L_SETSU_BUDGET = 546.9
CODE_EDGES = [35.6, 52.2, 68.8]          # kan / kou / moku code xMax
NAME_STARTS = [39.2, 55.7, 73.0]         # kan / kou / moku name x0 anchors
SETSU_CODE_X0 = (427.0, 439.0)
SETSU_NAME_X0 = (439.0, 491.0)
# Right-half (translated) right-edges: executed, carry x3, unspent; ratio zone.
R_MONEY = [102.2, 163.0, 223.8, 284.7, 345.5]
RATIO_X = (358.0, 391.0)
ORD_X0 = 394.1
PROJ_LABEL_X0 = (408.0, 552.0)
PROJ_TOTAL_EDGE = 547.7
# Control pages
LIST_EDGES = [278.4, 385.8, 507.3]
SOUKATSU_EDGES = [212.8, 290.2, 363.5, 433.5]
SETSU_SUM_HALF = [(75.0, 215.0, 295.1), (305.0, 450.0, 529.1)]
JISSHITSU_EDGE = 490.0
FORMAL_CODE = [54.1, 242.0]
FORMAL_BUDGET = 535.5
FORMAL_R = [161.0, 287.0, 412.3, 538.0]

def parse_pages(raw):
    result = []
    for part in raw.decode('utf-8').split('<page ')[1:]:
        words = []
        for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"[^>]*>(.*?)</word>', part):
            words.append([*[float(m[i]) for i in range(1, 5)], html.unescape(m[5])])
        result.append(words)
    return result

def lines(words, lo=130.0, hi=782.0):
    out = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if not lo < w[1] < hi: continue
        if not out or w[1] - out[-1][0][1] > 1.0: out.append([])
        out[-1].append(w)
    return [sorted(r, key=lambda w: w[0]) for r in out]

def cell(row, edge, tol=1.0):
    return [w for w in row if abs(w[2] - edge) < tol and MONEY.fullmatch(w[4])]

def num(words):
    assert len(words) == 1, words
    return int(words[0][4].replace(',', '').replace('△', '-'))

def js(x): return json.dumps(x, ensure_ascii=False, separators=(',', ':'))

def halves(page_words, landscape):
    if not landscape: raise AssertionError
    left = [w for w in page_words if w[0] < 600]
    right = [[w[0]-OFF, w[1], w[2]-OFF, w[3], w[4]] for w in page_words if w[0] >= 600]
    return left, right

def decode_year(year, raw, config, approval):
    pages = parse_pages(raw)
    assert len(pages) == config['physical_pages']
    cover = ''.join(w[4] for w in pages[0])
    assert config['cover_year_text'] in cover and '歳入歳出決算書' in cover, (year, cover[:80])
    src = config['origin']; sha = src['sha256']
    financial = []; controls = []; projects = []
    landscape = config['layout'] == 'landscape'

    def base(a, p, y, role):
        ident = f'{sha}:{a["id"]}:{role}:{p}:{y:.6f}'
        hdr_page = pp_words[p-1]
        bill = approval.get(a['id']) or {}
        return dict(
            source_row_id=ident, jurisdiction_id='132071', fiscal_year=year,
            account_id=a['id'], account_name=a['name'], source_grain=role,
            phase='executed', unit='円',
            original_url=src['url'], original_sha256=sha, original_bytes=src['bytes'],
            physical_page=p,
            recognition_bill=bill.get('bill'), recognition_date=bill.get('recognition_date'),
            recognition_source_json=js(bill) if bill else None,
            submitted_date=None, statutory_setsu_id=None, department=None,
            header_source_json=js([w for w in hdr_page if w[1] < 130]),
            printed_page_label=''.join(w[4] for w in sorted(hdr_page, key=lambda w: w[0]) if w[1] > 785),
            account_title_physical_page=a['title_page'],
            account_title_source_json=js(pages[a['title_page']-1]))

    pp_words = pages
    for a in config['accounts']:
        contexts = [None, None, None]; last_legal = None; project_pending = None
        if landscape:
            spreads = [(p, pages[p-1], None) for p in range(a['detail_first'], a['detail_last']+1)]
        else:
            spreads = [(p, pages[p-1], pages[p]) for p in range(a['detail_first'], a['detail_last']+1, 2)]
        for p, lwords, rwords in spreads:
            if landscape:
                lwords, rwords = halves(lwords, True)
                lpage = rpage = p
            else:
                lpage, rpage = p, p+1
            assert any('当初予算額' in w[4] for w in lwords if w[1] < 140), (a['id'], lpage)
            assert any('補正予算額' in w[4] for w in lwords if w[1] < 140), (a['id'], lpage)
            assert any(w[4] == '支出済額' for w in rwords if w[1] < 140), (a['id'], rpage)
            assert any('単位：円' in w[4] or '（単位：円）' in w[4] for w in rwords if w[1] < 140), (a['id'], rpage)
            rlines = lines(rwords); bands = []
            for row in lines(lwords):
                y = row[0][1]
                pair = [r for r in rlines if abs(r[0][1] - y) < .8]
                hcodes = [[w for w in row if abs(w[2] - e) < 1.5 and re.fullmatch(r'\d+', w[4])] for e in CODE_EDGES]
                b = [cell(row, e, 2.0) for e in L_MONEY]
                budget = all(len(c) == 1 for c in b)
                level = next((i for i in [2, 1, 0] if hcodes[i]), None)
                if level is not None and budget:
                    assert all(not hcodes[i] or (contexts[i] and hcodes[i][0][4] == contexts[i]['code']) for i in range(level)), (lpage, y, row)
                    name = [w for w in row if NAME_STARTS[level] - 2.0 <= w[0] < 125]
                    contexts[level] = {'code': hcodes[level][0][4], 'parts': [w[4] for w in name], 'words': name}
                    for i in range(level+1, 3): contexts[i] = None
                    last_legal = None
                elif level is not None:
                    for i, cc in enumerate(hcodes):
                        if cc and contexts[i]: assert cc[0][4] == contexts[i]['code'], (lpage, y, i, cc, contexts)
                if level is None:
                    for i, start in enumerate(NAME_STARTS):
                        tail = [w for w in row if abs(w[0] - start) < 1.8 and w[2] < 125 and not MONEY.fullmatch(w[4])]
                        if tail and contexts[i]:
                            contexts[i]['parts'] += [w[4] for w in tail]; contexts[i]['words'] += tail
                codes = [w for w in row if SETSU_CODE_X0[0] < w[0] < SETSU_CODE_X0[1] and re.fullmatch(r'\d{1,2}', w[4])]
                lc = cell(row, L_SETSU_BUDGET, 2.0)
                hierarchy = budget and level is not None
                total = '歳出合計' in ''.join(w[4] for w in row) and len(b[-1]) == 1
                if codes or (hierarchy and budget) or total:
                    assert len(pair) == 1, (lpage, y, pair)
                    r = pair[0]
                    money = [cell(r, e, 1.7) for e in R_MONEY]
                    assert all(len(c) == 1 for c in money), (lpage, y, money)
                    values = [num(c) for c in money]
                    ratio = [w for w in r if RATIO_X[0] < w[0] < RATIO_X[1] and re.fullmatch(r'[\d.]+', w[4])]
                    assert len(ratio) == 1, (lpage, y, ratio)
                    islegal = bool(codes)
                    role = 'printed_legal_setsu' if islegal else ('account_control' if total else ['kan_control', 'kou_control', 'moku_control'][level])
                    obj = base(a, lpage, y, role)
                    obj.update(
                        printed_setsu_code=codes[0][4] if islegal else None,
                        printed_setsu_name=None,
                        amount_executed=values[0], carry_continuing=values[1],
                        carry_authorized=values[2], carry_accident=values[3],
                        amount_unspent=values[4], printed_execution_ratio=ratio[0][4],
                        budget_initial=None, budget_supplementary=None,
                        budget_prior_carry=None, budget_reserve_transfer=None,
                        budget_current=num(lc) if islegal else (num(b[-1]) if len(b[-1])==1 else None),
                        paired_physical_page=None if landscape else rpage,
                        raw_left_row_json=js(row),
                        raw_right_row_json=js([w for w in r if w[0] < RATIO_X[1]]),
                        money_cells_json=js({'left': lc if islegal else b, 'right': money, 'ratio': ratio}),
                        hierarchy_source_json=None, _context=tuple(contexts), _label_words=[])
                    if not islegal:
                        for key, c in zip(['budget_initial', 'budget_supplementary', 'budget_prior_carry', 'budget_reserve_transfer', 'budget_current'], b):
                            obj[key] = num(c) if len(c)==1 else None
                        if all(v is not None for v in [obj['budget_initial'],obj['budget_supplementary'],obj['budget_prior_carry'],obj['budget_reserve_transfer'],obj['budget_current']]):
                            assert obj['budget_initial'] + obj['budget_supplementary'] + obj['budget_prior_carry'] + obj['budget_reserve_transfer'] == obj['budget_current'], (lpage, y, obj)
                    assert sum(values) == obj['budget_current'], (lpage, y, obj)
                    if islegal:
                        assert all(contexts), (lpage, y, contexts)
                        financial.append(obj); last_legal = obj
                    else:
                        controls.append(obj)
                labels = [w for w in row if SETSU_NAME_X0[0] < w[0] < SETSU_NAME_X0[1] and not MONEY.fullmatch(w[4])]
                if labels and last_legal: last_legal['_label_words'] += labels
                if contexts[2]: bands.append((y, tuple(contexts)))
            for row in rlines:
                y = row[0][1]
                start = [w for w in row if abs(w[0] - ORD_X0) < 1.8 and re.fullmatch(r'\d{3}', w[4])]
                if start:
                    assert project_pending is None, (rpage, y, project_pending)
                    ctx = next((c for yy, c in reversed(bands) if yy <= y + .8), tuple(contexts))
                    project_pending = {'code': start[0][4], 'words': list(row), 'context': ctx,
                                       'page': rpage, 'y': y,
                                       'parts': [w[4] for w in row if PROJ_LABEL_X0[0] < w[0] < PROJ_LABEL_X0[1] and not MONEY.fullmatch(w[4])],
                                       'amount_words': None}
                elif project_pending:
                    project_pending['words'] += row
                    project_pending['parts'] += [w[4] for w in row if PROJ_LABEL_X0[0] < w[0] < PROJ_LABEL_X0[1] and not MONEY.fullmatch(w[4])]
                # First remark-zone money after an ordinal is the printed project
                # total; its column differs by year (547.x or 555.x), verified by
                # per-moku reconciliation, never by position assumptions alone.
                amounts = [w for w in row if w[0] > 460 and 544 < w[2] < 572 and MONEY.fullmatch(w[4])][:1]
                if project_pending and amounts:
                    assert len(amounts) == 1
                    q = project_pending
                    obj = base(a, q['page'], q['y'], 'project_control')
                    obj.update(printed_project_ordinal=q['code'],
                               printed_project_label=''.join(q['parts']),
                               amount_executed=num(amounts),
                               raw_project_json=js(q['words']),
                               money_cells_json=js(amounts), _context=q['context'])
                    projects.append(obj); project_pending = None
            if landscape:
                pass
        assert project_pending is None, (a['id'], project_pending)
    # Account list rows (歳出決算額 = middle money column), once per book.
    lrows = [row for row in lines(pages[config['account_list_page']-1], lo=140, hi=780)]
    triples = [row for row in lrows if len([w for w in row if 300 < w[0] and w[2] < 396 and MONEY.fullmatch(w[4])]) == 1 and len([w for w in row if w[0] > 195 and MONEY.fullmatch(w[4])]) == 3]
    assert len(triples) == len(config['accounts']) + 1, (year, len(triples))
    for acc, row in zip(config['accounts'], triples):
        money = [w for w in row if 300 < w[0] < 395 and MONEY.fullmatch(w[4])]
        obj = base(acc, config['account_list_page'], row[0][1], 'account_overview_control')
        obj.update(amount_executed=num(money), raw_control_json=js(row), money_cells_json=js(money),
                   account_list_row_json=js(row))
        controls.append(obj)
    trow = triples[-1]
    tm = [w for w in trow if 300 < w[0] < 395 and MONEY.fullmatch(w[4])]
    obj = base(config['accounts'][0], config['account_list_page'], trow[0][1], 'account_list_grand_total_control')
    # Whole-book 合計 row: printed on the global account-list page, not inside
    # any single account — do not assert the first account's title/recognition.
    obj.update(account_id='_all', account_name='合計', amount_executed=num(tm),
               account_title_physical_page=None, account_title_source_json=None,
               raw_control_json=js(trow), money_cells_json=js(tm))
    controls.append(obj)
    for a in config['accounts']:
        # Setsu summary: two printed column halves + subtotals + grand total.
        for row in lines(pages[a['setsu_summary']-1]):
            y = row[0][1]
            if not 150 < y < 780: continue
            for lo, hi, edge in SETSU_SUM_HALF:
                ws = [w for w in row if lo < w[0] < hi]; am = cell(row, edge, .8)
                text = ''.join(w[4] for w in ws)
                if '小計' in text and am:
                    obj = base(a, a['setsu_summary'], y, f'setsu_summary_subtotal_{int(edge)}_control')
                    obj.update(amount_executed=num(am), raw_control_json=js(ws + am), money_cells_json=js(am))
                    controls.append(obj); continue
                match = re.match(r'^(\d{1,2})(\D.*)$', text) if ws else None
                if match and am:
                    obj = base(a, a['setsu_summary'], y, f'setsu_summary_{int(lo)}_control')
                    obj.update(printed_setsu_code=match[1], printed_setsu_name=match[2],
                               amount_executed=num(am), raw_control_json=js(ws + am), money_cells_json=js(am))
                    controls.append(obj)
            if '合計' in ''.join(w[4] for w in row if w[0] < 300):
                am = [w for w in row if 390 < w[0] < 475 and MONEY.fullmatch(w[4])]
                if am:
                    obj = base(a, a['setsu_summary'], y, 'setsu_summary_grand_total_control')
                    obj.update(amount_executed=num(am), raw_control_json=js(row), money_cells_json=js(am))
                    controls.append(obj)
        # Real-surplus statement reference amounts (not expenditure rows).
        for row in lines(pages[a['jisshitsu']-1]):
            am = [w for w in row if w[0] > 380 and abs(w[2] - JISSHITSU_EDGE) < 1.2 and MONEY.fullmatch(w[4])]
            if am:
                obj = base(a, a['jisshitsu'], row[0][1], 'real_surplus_reference_control')
                obj.update(phase=None, amount_executed=None, printed_reference_amount=num(am),
                           raw_control_json=js(row), money_cells_json=js(am))
                controls.append(obj)
        # Soukatsu 歳出 summary rows (kan-level): 現額 = 支出 + 繰越 + 不用.
        # Column right-edges differ between accounts; measure the four dominant
        # money columns from this actual page (ratio/構成比 columns excluded).
        scols=[]
        for w in pages[a['soukatsu']-1]:
            if w[1]>150 and w[0]>140 and MONEY.fullmatch(w[4]) and w[2]<450:
                for e in scols:
                    if abs(e-w[2])<1.2: break
                else: scols.append(w[2])
        scols=sorted(scols)
        assert len(scols)>=4,(a['id'],scols)
        scols=scols[-4:]
        for row in lines(pages[a['soukatsu']-1]):
            y = row[0][1]
            cells4 = [cell(row, e, .9) for e in scols]
            if not all(len(c) == 1 for c in cells4): continue
            values = [num(c) for c in cells4]
            assert values[0] == sum(values[1:]), (a['id'], y, values)
            code = [w for w in row if 48 < w[0] < 60 and re.fullmatch(r'\d+', w[4])]
            label = ''.join(w[4] for w in row if 58 < w[0] < 160 and not MONEY.fullmatch(w[4]))
            role = 'account_summary_total_control' if '計' in label or '合' in label else 'account_kan_summary_control'
            obj = base(a, a['soukatsu'], y, role)
            obj.update(kan_code=code[0][4] if code else None, printed_control_label=label,
                       budget_current=values[0], amount_executed=values[1],
                       carry_total=values[2], amount_unspent=values[3],
                       raw_control_json=js(row), money_cells_json=js(cells4))
            controls.append(obj)
        # Formal settlement (款項) rows.
        kan = None
        for p in a['formal_pages']:
            if landscape:
                lwords, rwords = halves(pages[p-1], True); lp = rp = p
            else:
                lwords, rwords = pages[p-1], pages[p]; lp, rp = p, p+1
            rlines2 = lines(rwords, lo=95)
            for row in lines(lwords, lo=95):
                y = row[0][1]
                bc = cell(row, FORMAL_BUDGET, 1.0)
                if not bc: continue
                pair = [r for r in rlines2 if abs(r[0][1] - y) < 1.0]
                assert len(pair) == 1, (lp, y)
                cells4 = [cell(pair[0], e, 1.0) for e in FORMAL_R]
                assert all(len(c) == 1 for c in cells4), (lp, y, cells4)
                values = [num(c) for c in cells4]
                assert num(bc) == sum(values[:3]), (a['id'], lp, y)
                assert values[3] == values[1] + values[2], (a['id'], lp, y, values)
                kc = [w for w in row if abs(w[2] - FORMAL_CODE[0]) < 1 and re.fullmatch(r'\d+', w[4])]
                oc = [w for w in row if abs(w[2] - FORMAL_CODE[1]) < 1 and re.fullmatch(r'\d+', w[4])]
                if kc: kan = kc[0][4]
                obj = base(a, lp, y, 'formal_settlement_control')
                obj.update(kan_code=kan if kc or oc else None,
                           kou_code=oc[0][4] if oc else None,
                           printed_control_label=''.join(w[4] for w in row if w[0] < 440 and not MONEY.fullmatch(w[4])),
                           budget_current=num(bc), amount_executed=values[0],
                           carry_total=values[1], amount_unspent=values[2],
                           printed_budget_minus_executed=values[3],
                           paired_physical_page=None if landscape else rp,
                           raw_control_json=js(row), raw_right_row_json=js(pair[0]),
                           money_cells_json=js({'left': bc, 'right': cells4}))
                controls.append(obj)
    for obj in financial + controls + projects:
        context = obj.pop('_context', None)
        if context:
            for k, v in zip(['kan', 'kou', 'moku'], context):
                obj[k + '_code'] = v['code'] if v else None
                obj[k + '_name'] = ''.join(v['parts']) if v else None
            obj['hierarchy_source_json'] = js(context)
        if '_label_words' in obj:
            words = obj.pop('_label_words')
            obj['printed_setsu_name'] = ''.join(w[4] for w in words) if words else None
            obj['printed_label_cells_json'] = js(words)
    # Reserve moku rows print no setsu; retain as financial rows with NULL codes.
    for a in config['accounts']:
        reserves = [r for r in controls if r['account_id'] == a['id'] and r['source_grain'] == 'moku_control' and r['moku_name'] == '予備費']
        for r0 in reserves:
            obj = dict(r0)
            obj['control_source_row_id'] = obj['source_row_id']
            obj['source_row_id'] = obj['source_row_id'].replace('moku_control', 'printed_reserve_moku')
            obj['source_grain'] = 'printed_reserve_moku'
            obj['printed_setsu_code'] = None; obj['printed_setsu_name'] = None
            assert obj['amount_executed'] == 0, obj['source_row_id']
            financial.append(obj)
    for role, rows in [('financial', financial), ('controls', controls), ('projects', projects)]:
        for a in config['accounts']:
            ordered = sorted([r for r in rows if r['account_id'] == a['id']],
                             key=lambda r: (r['physical_page'], r['source_row_id']))
            for i, r in enumerate(ordered, 1):
                r['source_row_ordinal'] = i
                r['source_table_id'] = f'akishima-fy{year}-settlement-{a["id"]}-{role}'
    return {'financial': financial, 'controls': controls, 'projects': projects}, pages
