"""Emit the 132039 enterprise-statement layout from measured rule geometry.

Phase A writes grids/spreads/detail books/notes/exclusion regions/metadata in
pt (origin render geometry in 300dpi px, x0.24). Phase B (--native) verifies
the native SHA, binds printed header cells and confirmed-blank cells to real
observation ids, and writes the finalized layout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ingestion.lib.pdf_table import tokens_from_ocr
from ingestion.fiscal.layouts.statement.text_spread import inside

SCALE = 72 / 300
SOURCE_SHA = '84743fdd8cf408d7c7f9cbe4e92cdea0708cabfe2407421286eb91db93e783b0'


def pt(*px):
    return [round(v * SCALE, 4) for v in px]


def rules(page):
    g = json.loads((Path(__file__).resolve().parents[4] /
        'observations/scan-2025-devin-max-2026-10-09/132039/water/origin/geometry.json')
        .read_text())
    return g[str(page)]


def bands(page, top_index, bottom_index):
    """Data bands between consecutive horizontal rules top_index..bottom_index."""
    hs = rules(page)['horizontal_rules']
    return [pt(hs[i]['y'], hs[i + 1]['y']) for i in range(top_index, bottom_index)]


def grid(table, page, printed, columns, bands_, required):
    return {'table': table, 'page': page, 'printed_page': printed,
            'columns': [dict(name=n, left=round(l * SCALE, 4), right=round(r * SCALE, 4),
                             **({'anchor': a} if a else {}), **({'separator': s} if s else {}))
                        for n, l, r, a, s in columns],
            'bands': bands_, 'required_cells': required}


SU_PREFIX = '地方公営企業法第26条第2項の規定による繰越額'
SH_PREFIX = '地方公営企業法第26条の規定による繰越額'
ZEI = '継続費逓次繰越額'


def base_layout(native_sha=None):
    suieki_bands = bands(6, 9, 14)   # rules 9..14 → 5 data bands (1640..2390)
    shihon_bands = bands(8, 9, 13)   # rules 9..13 → 4 data bands (1565.5..1993.5)
    suieki_left = grid('suieki_shishutsu', 6, 2, [
        ('区分', 194, 615.5, 'center', ''),
        ('当初予算額', 615.5, 896.5, 'center', ''),
        ('補正予算額', 896.5, 1177.5, 'center', ''),
        ('予備費支出額', 1177.5, 1412.0, 'center', ''),
        ('流用増減額', 1412.0, 1646.5, 'center', ''),
        ('地方公営企業法第24条第3項の規定による支出額', 1646.5, 1897.5, 'center', ''),
        ('小計', 1897.5, 2179.0, 'center', ''),
    ], suieki_bands, ['区分', '当初予算額', '補正予算額', '予備費支出額', '流用増減額',
                      '地方公営企業法第24条第3項の規定による支出額', '小計'])
    suieki_right = grid('suieki_shishutsu', 7, 3, [
        (SU_PREFIX + '_予算', 232.5, 544.5, 'center', ''),
        ('合計_予算', 544.5, 825.5, 'center', ''),
        ('決算額', 825.5, 1106.5, 'center', ''),
        (SU_PREFIX + '_決算', 1106.5, 1381.5, 'center', ''),
        ('不用額', 1381.5, 1662.5, 'center', ''),
        ('備考', 1662.5, 2248.5, 'center', '\n'),
    ], suieki_bands, [SU_PREFIX + '_予算', '合計_予算', '決算額', SU_PREFIX + '_決算', '不用額'])
    shihon_left = grid('shihon_shishutsu', 8, 4, [
        ('区分', 194, 590.5, 'center', ''),
        ('当初予算額', 590.5, 909.5, 'center', ''),
        ('補正予算額', 909.5, 1120.5, 'center', ''),
        ('予備費支出額', 1120.5, 1307.5, 'center', ''),
        ('流用増減額', 1307.5, 1495.5, 'center', ''),
        ('小計', 1495.5, 1774.5, 'center', ''),
        (SH_PREFIX + '_予算', 1774.5, 1979.0, 'center', ''),
        (ZEI + '_予算', 1979.0, 2191.0, 'center', ''),
    ], shihon_bands, ['区分', '当初予算額', '補正予算額', '予備費支出額', '流用増減額', '小計',
                      SH_PREFIX + '_予算', ZEI + '_予算'])
    shihon_right = grid('shihon_shishutsu', 9, 5, [
        ('合計_予算', 194, 474.5, 'center', ''),
        ('決算額', 474.5, 785.5, 'center', ''),
        (SH_PREFIX + '_翌年度', 785.5, 995.5, 'center', ''),
        (ZEI + '_翌年度', 995.5, 1207.5, 'center', ''),
        ('合計_翌年度', 1207.5, 1417.5, 'center', ''),
        ('不用額', 1417.5, 1675.5, 'center', ''),
        ('備考', 1675.5, 2198.5, 'center', '\n'),
    ], shihon_bands, ['合計_予算', '決算額', SH_PREFIX + '_翌年度', ZEI + '_翌年度',
                      '合計_翌年度', '不用額'])

    detail_cols = [('款', 475.0, 719.0, 'center', ''), ('項', 719.0, 894.5, 'center', ''),
                   ('目', 894.5, 1251.5, 'center', ''), ('節', 1251.5, 1745.5, 'center', ''),
                   ('金額', 1745.5, 2050.5, 'center', '')]
    detail_cols_42 = [('款', 407.0, 673.5, 'center', ''), ('項', 673.5, 864.0, 'center', ''),
                      ('目', 864.0, 1253.5, 'center', ''), ('節', 1253.5, 1791.0, 'center', ''),
                      ('金額', 1791.0, 2124.0, 'center', '')]
    shuueki_pages = [
        grid('shuueki_hiyou_meisai', 39, 35, detail_cols, bands(39, 1, 33), ['金額']),
        grid('shuueki_hiyou_meisai', 40, 36, detail_cols, bands(40, 1, 38), ['金額']),
        grid('shuueki_hiyou_meisai', 41, 37, detail_cols, bands(41, 1, 44), ['金額'])]
    shihon_pages = [
        grid('shihon_shushi_meisai', 42, 38, detail_cols_42, bands(42, 14, 42), ['金額'])]

    return {
        'source_sha256': SOURCE_SHA,
        'native_sha256': native_sha,
        'account': '水道事業会計',
        'scope': [[6, 9], [38, 43]],
        'pages': [6, 7, 8, 9, 38, 39, 40, 41, 42, 43],
        'spreads': [
            {'id': 'suieki_shishutsu', 'left': suieki_left, 'right': suieki_right},
            {'id': 'shihon_shishutsu', 'left': shihon_left, 'right': shihon_right}],
        'detail_books': [
            {'id': 'shuueki_hiyou_meisai', 'pages': shuueki_pages},
            {'id': 'shihon_shushi_meisai', 'pages': shihon_pages}],
        'notes': NOTES,
        'exclusion_regions': EXCLUSIONS,
        'corrections': CORRECTIONS,
        'metadata': METADATA,
        'amount_columns': AMOUNT_COLUMNS,
        'header_bindings': [],
    }


NOTE = [
    # (kind, page, printed, [px bbox]) — regions mutually disjoint, outside
    # expenditure grid bounds and exclusion regions; fitted to native token extents.
    ('書名', 6, 2, [180, 280, 1200, 370]),
    ('節標題', 6, 2, [140, 330, 900, 424]),
    ('収支区分', 6, 2, [140, 480, 700, 560]),
    ('収支区分', 6, 2, [140, 1230, 700, 1414]),
    ('単位', 7, 3, [1780, 480, 2260, 560]),
    ('単位', 7, 3, [1780, 1360, 2260, 1414]),
    ('節標題', 8, 4, [140, 310, 900, 414]),
    ('収支区分', 8, 4, [140, 415, 700, 485]),
    ('収支区分', 8, 4, [140, 1180, 700, 1339]),
    ('脚注', 8, 4, [140, 2000, 2230, 2200]),
    ('単位', 9, 5, [1780, 410, 2210, 485]),
    ('単位', 9, 5, [1780, 1280, 2210, 1345]),
    ('書名', 38, 34, [420, 330, 1350, 395]),
    ('収支区分', 38, 34, [140, 390, 700, 465]),
    ('単位', 38, 34, [1400, 340, 2100, 444]),
    ('収支区分', 39, 35, [140, 240, 700, 354]),
    ('単位', 39, 35, [1400, 240, 2100, 354]),
    ('単位', 40, 36, [1400, 240, 2100, 354]),
    ('単位', 41, 37, [1400, 240, 2100, 354]),
    ('書名', 42, 38, [140, 170, 2100, 316]),
    ('収支区分', 42, 38, [140, 315, 700, 385]),
    ('単位', 42, 38, [1400, 317, 2150, 369]),
    ('収支区分', 42, 38, [140, 1180, 700, 1311]),
    ('単位', 42, 38, [1400, 1180, 2150, 1311]),
]
for _p, _pp in [(6, 2), (7, 3), (8, 4), (9, 5), (38, 34), (39, 35), (40, 36), (41, 37),
                (42, 38)]:
    NOTE.append(('頁番号', _p, _pp, [1000, 3380, 1500, 3480]))
NOTES = [{'kind': k, 'page': p, 'printed_page': pp, 'bbox': pt(*b)} for k, p, pp, b in NOTE]

EXCLUSIONS = [
    {'region': '収入表', 'reason': '収益的収入及び支出の収入表は歳出範囲外', 'page': 6,
     'bbox': pt(150, 535, 2200, 1210)},
    {'region': '収入表', 'reason': '収益的収入及び支出の収入表は歳出範囲外', 'page': 7,
     'bbox': pt(150, 535, 2260, 1210)},
    {'region': '収入表', 'reason': '資本的収入及び支出の収入表は歳出範囲外', 'page': 8,
     'bbox': pt(150, 460, 2210, 1135)},
    {'region': '収入表', 'reason': '資本的収入及び支出の収入表は歳出範囲外', 'page': 9,
     'bbox': pt(150, 460, 2210, 1135)},
    {'region': '収入明細表', 'reason': '収益費用明細書の収入側は歳出範囲外', 'page': 38,
     'bbox': pt(150, 445, 2070, 2350)},
    {'region': '収入明細表', 'reason': '資本的収入支出明細書の収入側は歳出範囲外', 'page': 42,
     'bbox': pt(150, 370, 2150, 1190)},
]


def _correction(page, table, row, column, bbox_px, after, reason):
    return {'page': page, 'table': table, 'row': row, 'column': column,
            'bbox': pt(*bbox_px), 'observation_ids': [],
            'source_sha256': SOURCE_SHA, 'native_sha256': None,
            'before': None, 'after': after, 'reason': reason, 'native_observations': []}


def _glyph(page, table, row, column, before, after, reason):
    """Source-confirmed glyph fix on an observed cell; finalize() binds the
    native observation ids and the spec-derived cell bbox."""
    return {'page': page, 'table': table, 'row': row, 'column': column,
            'bbox': None, 'observation_ids': [],
            'source_sha256': SOURCE_SHA, 'native_sha256': None,
            'before': before, 'after': after, 'reason': reason, 'native_observations': []}


def _note(page, row, before, after, reason):
    """Source-confirmed text fix on a statement_notes row (1-based note index)."""
    return {'page': page, 'table': 'statement_notes', 'row': row, 'column': '注記',
            'bbox': None, 'observation_ids': [],
            'source_sha256': SOURCE_SHA, 'native_sha256': None,
            'before': before, 'after': after, 'reason': reason, 'native_observations': []}


_BLANK = '原典画像の罫線内を確認した印字空欄。OCR未観測一般を空欄と扱う規則ではない。'
_GLYPH = '原典画像で印字文字を確認。native生文字は維持し、セル所属・ID・bboxへ限定した字形訂正。'
CORRECTIONS = [
    _correction(7, 'suieki_shishutsu', 4, '備考', (1662.5, 2176.0, 2248.5, 2283.0), '', _BLANK),
    _correction(7, 'suieki_shishutsu', 5, '備考', (1662.5, 2283.0, 2248.5, 2390.0), '', _BLANK),
    _correction(9, 'shihon_shishutsu', 3, '備考', (1675.5, 1779.5, 2198.5, 1886.5), '', _BLANK),
    _correction(9, 'shihon_shishutsu', 4, '備考', (1675.5, 1886.5, 2198.5, 1993.5), '', _BLANK),
    _glyph(6, 'suieki_shishutsu', 2, '地方公営企業法第24条第3項の規定による支出額', 'o', '0',
           _GLYPH + '第1項行の印字0をnativeは小文字oと読んだ。'),
    _glyph(6, 'suieki_shishutsu', 4, '地方公営企業法第24条第3項の規定による支出額', 'o', '0',
           _GLYPH + '第3項行の印字0をnativeは小文字oと読んだ。'),
    _glyph(39, 'shuueki_hiyou_meisai', 2, '項', '営業費用', '1 営業費用',
           _GLYPH + '項標題の印字番号1がnativeで欠落。'),
    _glyph(39, 'shuueki_hiyou_meisai', 3, '目', '原水及び浄水費', '1 原水及び浄水費',
           _GLYPH + '目標題の印字番号1がnativeで欠落。'),
    _glyph(41, 'shuueki_hiyou_meisai', 30, '節', '時借入金利息', '一時借入金利息',
           _GLYPH + '節標題の先頭一字がnativeで欠落。'),
    _glyph(42, 'shihon_shushi_meisai', 23, '項', '企業債償還金', '2 企業債償還金',
           _GLYPH + '項標題の印字番号2がnativeで欠落。'),
    _glyph(41, 'shuueki_hiyou_meisai', 23, '節', 'リース資產減価償却費', 'リース資産減価償却費',
           _GLYPH + '印字は上部が立の二斜点と水平線の産U+7523。nativeは產U+7522と読んだ。'),
    _glyph(41, 'shuueki_hiyou_meisai', 24, '目', '7資產減耗費', '7資産減耗費',
           _GLYPH + '印字は産U+7523。nativeは產U+7522と読んだ。'),
    _glyph(41, 'shuueki_hiyou_meisai', 25, '節', '固定資產除却費', '固定資産除却費',
           _GLYPH + '印字は産U+7523。nativeは產U+7522と読んだ。'),
    _glyph(41, 'shuueki_hiyou_meisai', 34, '節', 'その他雑支出 (課税)', 'その他雑支出 （課税）',
           _GLYPH + '印字の両括弧は全角。nativeは半角と読んだ。'),
    _glyph(41, 'shuueki_hiyou_meisai', 35, '節', 'その他雑支出 （不課税)', 'その他雑支出 （不課税）',
           _GLYPH + '印字の閉括弧は全角。nativeは半角と読んだ。'),
    _glyph(7, 'suieki_shishutsu', 1, '備考',
           'うち仮払消費税\n及び地方消費税246, 738, 198)\n（うち納付消費税8,976,500)',
           '（うち仮払消費税\n及び地方消費税246, 738, 198)\n（うち納付消費税8,976,500)',
           _GLYPH + '仮払税額の開き括弧の印字を確認。nativeは検出せず欠落。'),
    _glyph(7, 'suieki_shishutsu', 2, '備考',
           'うち仮払消費税\n及び地方消費税246, 669, 394)',
           '（うち仮払消費税\n及び地方消費税246, 669, 394)',
           _GLYPH + '仮払税額の開き括弧の印字を確認。nativeは検出せず欠落。'),
    _glyph(7, 'suieki_shishutsu', 3, '備考',
           'うち仮払消費税\n68,804)\n及び地方消費税\n（うち納付消費税8, 976, 500 )',
           '（うち仮払消費税\n及び地方消費税68,804)\n（うち納付消費税8, 976, 500 )',
           _GLYPH + '仮払税額の開き括弧の印字を確認。nativeは検出せず欠落。括弧は税名2行を囲むため、印字の論理読順では金額と閉括弧が税名末尾の及び地方消費税の後に来る。'),
    _glyph(9, 'shihon_shishutsu', 1, '備考',
           'うち仮払消費税\n及び地方消費税55, 783, 478 )',
           '（うち仮払消費税\n及び地方消費税55, 783, 478 )',
           _GLYPH + '仮払税額の開き括弧の印字を確認。nativeは検出せず欠落。'),
    _glyph(9, 'shihon_shishutsu', 2, '備考',
           'うち仮払消費税55, 783, 478 )\n及び地方消費税',
           '（うち仮払消費税\n及び地方消費税55, 783, 478 )',
           _GLYPH + '仮払税額の開き括弧の印字を確認。nativeは検出せず欠落。括弧は税名2行を囲むため、印字の論理読順では金額と閉括弧が税名末尾の及び地方消費税の後に来る。'),
    _note(8, 10,
          '資本的収入額が資本的支出額に不足する額616,370,281円は、過年度分損益勘定留保資金255,268,138円、\n'
          '当年度分損益勘定留保資金289,176,565円、当年度分消費税及び地方消費税資本的収支調整額53,180,861円、減債積立金\n'
          '18,744,717円で補塡した。',
          '※資本的収入額が資本的支出額に不足する額616,370,281円は、過年度分損益勘定留保資金255,268,138円、\n'
          '当年度分損益勘定留保資金289,176,565円、当年度分消費税及び地方消費税資本的収支調整額53,180,861円、減債積立金\n'
          '18,744,717円で補填した。',
          '原典画像で脚注先頭の印字※と末尾の填U+586Bを確認。nativeは※を検出枠内で認識せず欠落し、末尾を塡U+5861と読んだ。印字の填は右側上部が十の縦横交差。'),
    _note(42, 20, '令和7年度武蔵野市水道事業会計資本的収入支出明細書',
          '3 令和7年度武蔵野市水道事業会計資本的収入支出明細書',
          '原典画像で書名先頭の冊番号3を確認。nativeは欠落。'),
]


def _ctx(columns, header_path, grain, phase=None):
    out = {'columns': columns, 'header_path': header_path, 'grain_columns': grain}
    if phase:
        out['phase'] = phase
    return out


METADATA = {
    'suieki_shishutsu': {
        'units': [{'text': '円・税込', 'scope': {'kind': 'columns',
            'columns': ['当初予算額', '補正予算額', '予備費支出額', '流用増減額',
                        '地方公営企業法第24条第3項の規定による支出額', '小計',
                        SU_PREFIX + '_予算', '合計_予算', '決算額', SU_PREFIX + '_決算', '不用額']}}],
        'notes': [
            {'text': '収益的収入及び支出の支出側。同一印字名を持つ二つの繰越列（予算側=額欄内／決算側=独立欄）は別列のまま。', 'scope': {'kind': 'table'}},
            {'text': '第1款の款行と第1項〜第4項。計行なし。区分・金額は印字のまま。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            _ctx(['区分'], ['区分'], ['区分']),
            _ctx(['当初予算額'], ['予算額', '当初予算額'], ['区分']),
            _ctx(['補正予算額'], ['予算額', '補正予算額'], ['区分']),
            _ctx(['予備費支出額'], ['予算額', '予備費支出額'], ['区分']),
            _ctx(['流用増減額'], ['予算額', '流用増減額'], ['区分']),
            _ctx(['地方公営企業法第24条第3項の規定による支出額'],
                 ['予算額', '地方公営企業法第24条第3項の規定による支出額'], ['区分']),
            _ctx(['小計'], ['予算額', '小計'], ['区分']),
            _ctx([SU_PREFIX + '_予算'], ['予算額', SU_PREFIX], ['区分'], phase='予算側繰越'),
            _ctx(['合計_予算'], ['予算額', '合計'], ['区分'], phase='予算側合計'),
            _ctx(['決算額'], ['決算額'], ['区分']),
            _ctx([SU_PREFIX + '_決算'], [SU_PREFIX], ['区分'], phase='決算側繰越'),
            _ctx(['不用額'], ['不用額'], ['区分']),
            _ctx(['備考'], ['備考'], ['区分']),
            {'columns': ['印字区分', '款', '項', 'physical_page', 'right_page', 'printed_page',
                         'source_row', 'cell_refs', 'hierarchy_refs'],
             'header_path': None, 'grain_columns': ['区分'],
             'role': 'derived', 'note': '印字区分ラベル・継承した款/項・頁・行番号・原典binding参照'}]},
    'shihon_shishutsu': {
        'units': [{'text': '円・税込', 'scope': {'kind': 'columns',
            'columns': ['当初予算額', '補正予算額', '予備費支出額', '流用増減額', '小計',
                        SH_PREFIX + '_予算', ZEI + '_予算', '合計_予算', '決算額',
                        SH_PREFIX + '_翌年度', ZEI + '_翌年度', '合計_翌年度', '不用額']}}],
        'notes': [
            {'text': '資本的収入及び支出の支出側。予算側繰越列と翌年度繰越額欄の同名列（法26条・継続費逓次・合計）は別列のまま。', 'scope': {'kind': 'table'}},
            {'text': '第1款の款行と第1項〜第3項。計行なし。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            _ctx(['区分'], ['区分'], ['区分']),
            _ctx(['当初予算額'], ['予算額', '当初予算額'], ['区分']),
            _ctx(['補正予算額'], ['予算額', '補正予算額'], ['区分']),
            _ctx(['予備費支出額'], ['予算額', '予備費支出額'], ['区分']),
            _ctx(['流用増減額'], ['予算額', '流用増減額'], ['区分']),
            _ctx(['小計'], ['予算額', '小計'], ['区分']),
            _ctx([SH_PREFIX + '_予算'], ['予算額', SH_PREFIX], ['区分'], phase='予算側繰越'),
            _ctx([ZEI + '_予算'], ['予算額', ZEI], ['区分'], phase='予算側繰越'),
            _ctx(['合計_予算'], ['合計'], ['区分'], phase='予算側合計'),
            _ctx(['決算額'], ['決算額'], ['区分']),
            _ctx([SH_PREFIX + '_翌年度'], ['翌年度繰越額', SH_PREFIX], ['区分'], phase='翌年度繰越'),
            _ctx([ZEI + '_翌年度'], ['翌年度繰越額', ZEI], ['区分'], phase='翌年度繰越'),
            _ctx(['合計_翌年度'], ['翌年度繰越額', '合計'], ['区分'], phase='翌年度繰越'),
            _ctx(['不用額'], ['不用額'], ['区分']),
            _ctx(['備考'], ['備考'], ['区分']),
            {'columns': ['印字区分', '款', '項', 'physical_page', 'right_page', 'printed_page',
                         'source_row', 'cell_refs', 'hierarchy_refs'],
             'header_path': None, 'grain_columns': ['区分'],
             'role': 'derived', 'note': '印字区分ラベル・継承した款/項・頁・行番号・原典binding参照'}]},
    'shuueki_hiyou_meisai': {
        'units': [{'text': '円・税抜', 'scope': {'kind': 'columns',
            'columns': ['金額', '款_金額', '項_金額', '目_金額']}}],
        'notes': [
            {'text': '収益費用明細書の支出側。物理39-41頁の連続表。印字空欄の款・項・目セルは罫線の結合による継続で、継承値は款/項/目列、印字のままの値は印字名称列に入れる。', 'scope': {'kind': 'table'}},
            {'text': '企業会計の収益費用明細書に印字された款・項・目・節。普通会計の法定節の解釈や分類を付加しない。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            _ctx(['款', '款_金額'], ['款'], ['款']),
            _ctx(['項', '項_金額'], ['項'], ['款', '項']),
            _ctx(['目', '目_金額'], ['目'], ['款', '項', '目']),
            _ctx(['節', '金額'], ['節', '金額'], ['款', '項', '目', '節']),
            {'columns': ['印字区分', '印字名称', 'physical_page', 'printed_page',
                         'source_row', 'cell_refs'],
             'header_path': None, 'grain_columns': ['款', '項', '目', '節'],
             'role': 'derived', 'note': 'その行帯に印字された区分と名称の原文、頁・行番号、原典binding参照'}]},
    'shuueki_hiyou_meisai_details': {
        'units': [{'text': '円・税抜', 'scope': {'kind': 'columns',
            'columns': ['金額', '款_金額', '項_金額', '目_金額']}}],
        'notes': [{'text': '節末端行に款・項・目の継承経路と各親の印字小計を展開したもの。階層は罫線の結合と継続頁の空欄から復元。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            {'columns': ['印字区分', '印字名称', 'physical_page', 'printed_page',
                         'source_row', 'cell_refs', 'hierarchy_refs'],
             'header_path': None, 'grain_columns': ['款', '項', '目', '節'],
             'role': 'derived', 'note': 'その行帯に印字された区分と名称の原文、頁・行番号、原典binding参照'}]},
    'shihon_shushi_meisai': {
        'units': [{'text': '円・税抜', 'scope': {'kind': 'columns',
            'columns': ['金額', '款_金額', '項_金額', '目_金額']}}],
        'notes': [{'text': '資本的収入支出明細書の支出側（物理42頁下部）。継承と印字の分離は収益費用明細と同じ。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            _ctx(['款', '款_金額'], ['款'], ['款']),
            _ctx(['項', '項_金額'], ['項'], ['款', '項']),
            _ctx(['目', '目_金額'], ['目'], ['款', '項', '目']),
            _ctx(['節', '金額'], ['節', '金額'], ['款', '項', '目', '節']),
            {'columns': ['印字区分', '印字名称', 'physical_page', 'printed_page',
                         'source_row', 'cell_refs'],
             'header_path': None, 'grain_columns': ['款', '項', '目', '節'],
             'role': 'derived', 'note': 'その行帯に印字された区分と名称の原文、頁・行番号、原典binding参照'}]},
    'shihon_shushi_meisai_details': {
        'units': [{'text': '円・税抜', 'scope': {'kind': 'columns',
            'columns': ['金額', '款_金額', '項_金額', '目_金額']}}],
        'notes': [{'text': '節末端行に款・項・目の継承経路と各親の印字小計を展開したもの。', 'scope': {'kind': 'table'}}],
        'column_contexts': [
            {'columns': ['印字区分', '印字名称', 'physical_page', 'printed_page',
                         'source_row', 'cell_refs', 'hierarchy_refs'],
             'header_path': None, 'grain_columns': ['款', '項', '目', '節'],
             'role': 'derived', 'note': 'その行帯に印字された区分と名称の原文、頁・行番号、原典binding参照'}]},
    'statement_notes': {
        'units': [],
        'notes': [{'text': '節標題・収支区分ラベル・単位注記・印字頁番号・p8資本不足の※脚注など、表に入らない印字領域。注記内の金額は明細の金額列へ移さない。', 'scope': {'kind': 'table'}}],
        'column_contexts': []},
}

AMOUNT_COLUMNS = {
    'suieki_shishutsu': ['当初予算額', '補正予算額', '予備費支出額', '流用増減額',
        '地方公営企業法第24条第3項の規定による支出額', '小計', SU_PREFIX + '_予算',
        '合計_予算', '決算額', SU_PREFIX + '_決算', '不用額'],
    'shihon_shishutsu': ['当初予算額', '補正予算額', '予備費支出額', '流用増減額', '小計',
        SH_PREFIX + '_予算', ZEI + '_予算', '合計_予算', '決算額',
        SH_PREFIX + '_翌年度', ZEI + '_翌年度', '合計_翌年度', '不用額'],
    'shuueki_hiyou_meisai': ['金額', '款_金額', '項_金額', '目_金額'],
    'shuueki_hiyou_meisai_details': ['金額', '款_金額', '項_金額', '目_金額'],
    'shihon_shushi_meisai': ['金額', '款_金額', '項_金額', '目_金額'],
    'shihon_shushi_meisai_details': ['金額', '款_金額', '項_金額', '目_金額'],
    'statement_notes': [],
}


# header cells as (columns, header_path, [(page, printed, px bbox), ...])
# token selection happens against the actual native result in finalize().
HEADERS = [
    ('suieki_shishutsu', ['区分'], ['区分'],
     [(6, [(194.0, 1415.5, 615.5, 1640.0)])]),
    ('suieki_shishutsu', ['当初予算額'], ['予算額', '当初予算額'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(615.5, 1490.5, 896.5, 1640.0)])]),
    ('suieki_shishutsu', ['補正予算額'], ['予算額', '補正予算額'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(896.5, 1490.5, 1177.5, 1640.0)])]),
    ('suieki_shishutsu', ['予備費支出額'], ['予算額', '予備費支出額'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(1177.5, 1490.5, 1412.0, 1640.0)])]),
    ('suieki_shishutsu', ['流用増減額'], ['予算額', '流用増減額'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(1412.0, 1490.5, 1646.5, 1640.0)])]),
    ('suieki_shishutsu', ['地方公営企業法第24条第3項の規定による支出額'],
     ['予算額', '地方公営企業法第24条第3項の規定による支出額'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(1646.5, 1490.5, 1897.5, 1640.0)])]),
    ('suieki_shishutsu', ['小計'], ['予算額', '小計'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (6, [(1897.5, 1490.5, 2179.0, 1640.0)])]),
    ('suieki_shishutsu', [SU_PREFIX + '_予算'], ['予算額', SU_PREFIX],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (7, [(232.5, 1485.0, 544.5, 1640.0)])]),
    ('suieki_shishutsu', ['合計_予算'], ['予算額', '合計'],
     [(6, [(615.5, 1415.5, 2179.0, 1490.5)]), (7, [(232.5, 1415.5, 825.5, 1490.5)]),
      (7, [(544.5, 1490.5, 825.5, 1640.0)])]),
    ('suieki_shishutsu', ['決算額'], ['決算額'], [(7, [(825.5, 1415.5, 1106.5, 1640.0)])]),
    ('suieki_shishutsu', [SU_PREFIX + '_決算'], [SU_PREFIX],
     [(7, [(1100.0, 1415.5, 1381.5, 1640.0)])]),
    ('suieki_shishutsu', ['不用額'], ['不用額'], [(7, [(1381.5, 1415.5, 1662.5, 1640.0)])]),
    ('suieki_shishutsu', ['備考'], ['備考'], [(7, [(1662.5, 1415.5, 2248.5, 1640.0)])]),
    ('shihon_shishutsu', ['区分'], ['区分'],
     [(8, [(194.0, 1340.5, 590.5, 1565.5)])]),
    ('shihon_shishutsu', ['当初予算額'], ['予算額', '当初予算額'],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(585.0, 1415.5, 1125.0, 1565.5)])],
     'native OCRは印字セル当初予算額・補正予算額を1観測に併合した。両headerが同一観測を共有し、観測の生文字をそのままbindする。'),
    ('shihon_shishutsu', ['補正予算額'], ['予算額', '補正予算額'],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(585.0, 1415.5, 1125.0, 1565.5)])],
     'native OCRは印字セル当初予算額・補正予算額を1観測に併合した。両headerが同一観測を共有し、観測の生文字をそのままbindする。'),
    ('shihon_shishutsu', ['予備費支出額'], ['予算額', '予備費支出額'],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(1120.5, 1415.5, 1320.0, 1565.5)])]),
    ('shihon_shishutsu', ['流用増減額'], ['予算額', '流用増減額'],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(1300.0, 1415.5, 1500.0, 1565.5)])]),
    ('shihon_shishutsu', ['小計'], ['予算額', '小計'],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(1495.5, 1415.5, 1774.5, 1565.5)])]),
    ('shihon_shishutsu', [SH_PREFIX + '_予算'], ['予算額', SH_PREFIX],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(1774.5, 1415.5, 1979.0, 1565.5)])]),
    ('shihon_shishutsu', [ZEI + '_予算'], ['予算額', ZEI],
     [(8, [(590.5, 1340.5, 2191.0, 1415.5)]), (8, [(1970.0, 1415.5, 2198.0, 1565.5)])]),
    ('shihon_shishutsu', ['合計_予算'], ['合計'], [(9, [(194.0, 1340.5, 474.5, 1565.5)])]),
    ('shihon_shishutsu', ['決算額'], ['決算額'], [(9, [(474.5, 1340.5, 785.5, 1565.5)])]),
    ('shihon_shishutsu', [SH_PREFIX + '_翌年度'], ['翌年度繰越額', SH_PREFIX],
     [(9, [(785.5, 1340.5, 1417.5, 1415.5)]), (9, [(785.5, 1415.5, 995.5, 1565.5)])]),
    ('shihon_shishutsu', [ZEI + '_翌年度'], ['翌年度繰越額', ZEI],
     [(9, [(785.5, 1340.5, 1417.5, 1415.5)]), (9, [(985.0, 1415.5, 1210.0, 1565.5)])]),
    ('shihon_shishutsu', ['合計_翌年度'], ['翌年度繰越額', '合計'],
     [(9, [(785.5, 1340.5, 1417.5, 1415.5)]), (9, [(1207.5, 1415.5, 1417.5, 1565.5)])]),
    ('shihon_shishutsu', ['不用額'], ['不用額'], [(9, [(1417.5, 1340.5, 1675.5, 1565.5)])]),
    ('shihon_shishutsu', ['備考'], ['備考'], [(9, [(1675.5, 1340.5, 2198.5, 1565.5)])]),
]
def _detail_headers(table, pages, col_px, header_top, header_bottom):
    """Detail header bindings matching column_contexts groupings.

    款/項/目 each cover their name + inherited-amount columns; 節+金額 bind the
    two leaf cells together. Parts repeat on every page the header row prints."""
    groups = [(['款', '款_金額'], ['款'], col_px[0]), (['項', '項_金額'], ['項'], col_px[1]),
              (['目', '目_金額'], ['目'], col_px[2]),
              (['節', '金額'], ['節', '金額'], None)]
    for columns, path, cell in groups:
        boxes = []
        for page in pages:
            if cell is None:
                boxes.append((page, [(col_px[3][0], header_top, col_px[3][1], header_bottom),
                                     (col_px[4][0], header_top, col_px[4][1], header_bottom)]))
            else:
                boxes.append((page, [(cell[0], header_top, cell[1], header_bottom)]))
        HEADERS.append((table, columns, path, boxes))


_detail_headers('shuueki_hiyou_meisai', [39, 40, 41],
                [(475.0, 719.0), (719.0, 894.5), (894.5, 1251.5), (1251.5, 1745.5), (1745.5, 2050.5)],
                355.0, 416.0)
_detail_headers('shihon_shushi_meisai', [42],
                [(407.0, 673.5), (673.5, 864.0), (864.0, 1253.5), (1253.5, 1791.0), (1791.0, 2124.0)],
                1312.5, 1378.5)

HEADER_CONFIRM = ('原典画像の罫線・見開き・列見出しにより原文header_pathを復元。'
                  'nativeの誤認・欠落字は元文字を上書きせず原典確認宣言と分離。')


def finalize(layout, native):
    if hashlib.sha256(Path(native).read_bytes()).hexdigest() != layout['native_sha256']:
        raise ValueError('native SHA differs')
    result = json.loads(Path(native).read_text())
    if result['origin']['sha256'] != SOURCE_SHA:
        raise ValueError('native origin differs')
    tokens = tokens_from_ocr(result, kind='region', region_ids=['full-page'], unit='pt')
    by_page = {}
    for t in tokens:
        by_page.setdefault(t.page, []).append(t)
    bindings = []
    for decl in HEADERS:
        table, columns, path, parts = decl[:4]
        confirm = decl[4] if len(decl) > 4 else ''
        hparts = []
        for page, boxes in parts:
            for px in boxes:
                bounds = pt(*px)
                selected = [t for t in by_page.get(page, [])
                            if t.bbox and inside(t.bbox, bounds)]
                selected.sort(key=lambda t: (t.bbox.top, t.bbox.left, t.id))
                if not selected:
                    raise ValueError(f'Header cell empty: {table} {columns} p{page} {px}')
                hparts.append({'page': page, 'bbox': bounds,
                               'observation_ids': [t.id for t in selected],
                               'native_text': ''.join(t.raw_text for t in selected)})
        bindings.append({'table': table, 'columns': columns, 'header_path': path,
                         'source_sha256': SOURCE_SHA, 'native_sha256': layout['native_sha256'],
                         'parts': hparts, 'confirmation': HEADER_CONFIRM + confirm})
    specs = {}
    for spread in layout['spreads']:
        specs[(spread['left']['page'], spread['left']['table'])] = spread['left']
        specs[(spread['right']['page'], spread['right']['table'])] = spread['right']
    for book in layout['detail_books']:
        for spec in book['pages']:
            specs[(spec['page'], spec['table'])] = spec

    def grouped(tokens):
        lines = []
        for t in sorted(tokens, key=lambda t: (t.bbox.y('center'), t.bbox.left, t.id)):
            y = t.bbox.y('center')
            if lines and y - lines[-1][0] <= 4:
                lines[-1][1].append(t)
            else:
                lines.append([y, [t]])
        return [[''.join(t.raw_text for t in sorted(ws, key=lambda t: (t.bbox.left, t.id)))
                 for _, ws in lines]]

    for c in layout['corrections']:
        c['native_sha256'] = layout['native_sha256']
        if c['table'] == 'statement_notes':
            note = layout['notes'][c['row'] - 1]
            if note['page'] != c['page']:
                raise ValueError(f'Note correction row {c["row"]} is not page {c["page"]}')
            c['bbox'] = note['bbox']
            cell_tokens = sorted(
                (t for t in by_page.get(c['page'], []) if t.bbox and inside(t.bbox, note['bbox'])),
                key=lambda t: (t.bbox.top, t.bbox.left, t.id))
            if '\n'.join(grouped(cell_tokens)[0]) != c['before']:
                raise ValueError(f'Note correction before differs: {c["row"]}')
        elif c['before'] is None:
            cell_tokens = [t for t in by_page.get(c['page'], [])
                           if t.bbox and inside(t.bbox, c['bbox'])]
            if cell_tokens:
                raise ValueError(f'Confirmed-blank cell has observations: {c["table"]} r{c["row"]} {c["column"]}')
        else:
            spec = specs[(c['page'], c['table'])]
            col = next(col for col in spec['columns'] if col['name'] == c['column'])
            band = spec['bands'][c['row'] - 1]
            c['bbox'] = [col['left'], band[0], col['right'], band[1]]
            anchor = col.get('anchor', 'center')
            cell_tokens = sorted(
                (t for t in by_page.get(c['page'], []) if t.bbox
                 and ((col['left'] < t.bbox.x(anchor) <= col['right']) if anchor == 'right'
                      else (col['left'] <= t.bbox.x(anchor) < col['right']))
                 and band[0] <= t.bbox.y('center') < band[1]),
                key=lambda t: (t.bbox.left, t.bbox.top, t.id))
            if col.get('separator', '').join(grouped(cell_tokens)[0]) != c['before']:
                raise ValueError(f'Correction before differs: {c["table"]} r{c["row"]} {c["column"]}')
        c['observation_ids'] = [t.id for t in cell_tokens]
        c['native_observations'] = [{'id': t.id, 'sha256': layout['native_sha256']}
                                    for t in cell_tokens]
    layout['header_bindings'] = bindings
    return layout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    native_sha = None
    if args.native:
        native_sha = hashlib.sha256(args.native.read_bytes()).hexdigest()
    layout = base_layout(native_sha)
    if args.native:
        layout = finalize(layout, args.native)
    data = json.dumps(layout, ensure_ascii=False, indent=2) + '\n'
    args.output.write_text(data)
    print(json.dumps({'output': str(args.output), 'sha256': hashlib.sha256(data.encode()).hexdigest()}))


if __name__ == '__main__':
    main()
