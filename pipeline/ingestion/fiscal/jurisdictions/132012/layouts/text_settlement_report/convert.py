"""Assemble Hachioji's settlement report (主要な施策の成果・事務報告書) from Poppler word boxes.

The report is a selective narrative digest: each 款 opens a page with a fixed
7-part 決算額 decomposition (国庫支出金/都支出金/市債/その他/一般財源/執行率),
each 目 is printed as one heading line carrying 項番号+項名 and 目番号+目名 with
(予算現額)・当年度決算額・<前年度決算額>, and each listed 事業 block holds a
heading row, a prose description, numbered （n）内訳 items, finer ア/イ/ウ or
unnumbered sub-lines, a right-strip 財源内訳 list, and embedded stat tables.
Leaf rows are the finest printed amount lines; every other printed line in
scope is preserved as an annex line row. Amounts keep their printed text.
"""
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
FOOTER_TOP = 795
RIGHT_X = 405          # 財源内訳・事業金額欄の左端
NAME_RIGHT = 345       # 事業名の右端（担当課欄の手前）
NUM = re.compile(r'^[△\-]?[0-9]{1,3}(?:,[0-9]{3})*$|^[0-9]+$|^－$')
PAREN = re.compile(r'^[（(][0-9,]+[)）]$')
PREV = re.compile(r'^[<＜][0-9,]+[>＞]?$|^[>＞]$')
PREV_TEXT = re.compile(r'^[<＜][0-9,]+[>＞]$')
KOU_HEADING = re.compile(r'^([0-9]{1,2})項$')
MARKER_ITEM = re.compile(r'^[（(]([0-9]{1,2})[)）]')
MARKER_SUB = re.compile(r'^[ア-ン]$')
_MARKER_LEAD = re.compile(r'^[（(](?:[0-9]{1,2}|[ア-ン])[)）]')
COUNT_WORD = re.compile(r'^[0-9,]+[^\d,]+$')        # 「3人」「276件」など
UNIT_SUFFIX = re.compile(r'(円|件|人|回|日|部|％|%|千円|万円|名|台|か所|箇所|世帯|戸|枚|本|席|時間|年度|年)$')
AMOUNT_BAND = (225, 402)     # 内訳・細目の金額の右端帯（右寄せ）
KAN_KEYS = ['決算額', '国庫支出金', '都支出金', '市債', 'その他', '一般財源', '執行率']
DEFAULT_FUNDS = ['国庫支出金', '都支出金', '市債', 'その他', '一般財源']
DEPT_SUFFIX = re.compile(r'(課|部|室|局|館|所|係|会|場|園|校|庁|院|センター|棟|大学|組合|本部|事務所|ホール)$')
FUND_LABEL = re.compile(r'(金|料|債|財源|収入|税|費|寄附|積立|充当|繰入|分担|負担|使用|手数|広告|利子|交付|補助|助成|還付|雑入)')
FUND_DENY = re.compile(r'(額|計|状況|区分|件数|人数|割合|率|年度|収支|差額|対象)$')
LEAF_DENY = re.compile(r'(計|合計|差額|人数|件数|年度|平均|率|構成比|割合|回数|面積|日数|対象者数|利用者数)$')
AMOUNT_FULL = re.compile(r'^[△\-]?[0-9]{1,3}(?:,[0-9]{3})+$|^[0-9]{5,}$')
FUNDING_ECHO = re.compile(
    r'^(国庫支出金|都支出金|都総合交付金|市債|一般財源|その他|繰越金|繰入金|寄附金|'
    r'負担金|補助金|助成金|交付金|使用料|手数料|収入|返還金|入|出|財源|財源内訳|内訳)$')
# 内表（実績・収支・区分表）領域の認識: 短い表題行とスペース区切りのヘッダ行で開始し、
# 計数値セルを持たない行（散文）・マーカー行・見出しで終了する。
HEADER_TOKEN = re.compile(
    r'^(区|分|計|数|量|金|額|費|財|源|内|訳|等|名|内訳|区分|金額|内容|施設名|対象|'
    r'事業名|単価|月額|件数|人数|回数|日数|期間|収支|実績|状況|年度|摘要|項目|名称|'
    r'単位|利用|開催日)$')
NUMERIC_CELL = re.compile(
    r'^[△\-]?[0-9０-９,\.]+$|^[0-9０-９,\.]+[^\d,\s]+$|^[（(][0-9,\.]+[)）]$|'
    r'^[<＜][0-9,\.]+[>＞]$|^－$|^△$|\d[\d,\.]*$')
TABLE_TITLE_TAIL = re.compile(
    r'(状況|実績|内訳|一覧|明細|収支|結果|構成|割合|目標|概要|単価|給付額|支給額)$'
    r'|（単位|（ 単 位')


def table_like(words):
    """内表に属する行か: 計数値セルかヘッダ語を含む。"""
    return (sum(1 for w in words if NUMERIC_CELL.match(w['text'])) >= 1
            or sum(1 for w in words if HEADER_TOKEN.match(w['text'])) >= 2)


def table_start(words):
    """annex 送り行のうち、内表領域を開く行か（表題・ヘッダ・数値行）。"""
    if not words:
        return False
    if len(squashed(words)) <= 40 and TABLE_TITLE_TAIL.search(squashed(words)):
        return True
    return table_like(words)

DETAIL_COLUMNS = [
    '款_番号', '款_名称', '款_決算額', '款_国庫支出金', '款_都支出金', '款_市債',
    '款_その他', '款_一般財源', '款_執行率', '款_物理頁', '款_上端', '款_下端',
    '項_番号', '項_名称', '項_物理頁', '項_上端', '項_下端',
    '目_番号', '目_名称', '目_予算現額', '目_当年度決算額', '目_前年度決算額',
    '目_物理頁', '目_上端', '目_下端',
    '事業_番号', '事業_名称', '事業_担当課', '事業_予算現額', '事業_当年度決算額',
    '事業_前年度決算額', '事業_説明', '事業_物理頁', '事業_上端', '事業_下端',
    '内訳_番号', '内訳_名称', '内訳_金額', '内訳_物理頁', '内訳_上端', '内訳_下端',
    '細目_番号', '細目_名称', '細目_数量', '細目_金額', '細目_物理頁', '細目_上端', '細目_下端',
]


def detail_columns(funds):
    """明細表の列。funds は款見出しの資金分解5名。既定は一般会計と同一の並び。"""
    fund_cols = ['款_' + n for n in funds]
    if fund_cols == ['款_国庫支出金', '款_都支出金', '款_市債', '款_その他', '款_一般財源']:
        return [c for c in DETAIL_COLUMNS]
    out = []
    skip = {'款_国庫支出金', '款_都支出金', '款_市債', '款_その他', '款_一般財源'}
    inserted = False
    for c in DETAIL_COLUMNS:
        if c in skip:
            if not inserted:
                out.extend(fund_cols)
                inserted = True
            continue
        out.append(c)
    return out
FUNDING_COLUMNS = [
    '款_番号', '項_番号', '目_番号', '事業_番号', '事業_物理頁', '事業_上端',
    '財源_名称', '財源_金額', '財源_物理頁', '財源_上端', '財源_下端',
]
ANNEX_COLUMNS = [
    '款_番号', '項_番号', '目_番号', '事業_番号', '事業_物理頁', '事業_上端',
    '本文', '物理頁', '上端', '下端', '左端', '右端',
]


def squashed(words):
    return ''.join(w['text'] for w in words)


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(path).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - PAGE_WIDTH) > .5 or abs(float(page.get('height')) - PAGE_HEIGHT) > .5:
            raise ValueError(f'Unmeasured page dimensions at {number}')
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages.append((number, [w for w in words if w['text'].strip()]))
    if len(pages) != last - first + 1:
        raise ValueError('Incomplete Poppler page range')
    return pages


GLUED_PAREN = re.compile(r'^([（(][0-9,]+[)）])([0-9,]+)$')


def unglue(words):
    """「（N）M」や「M（N）」のように括弧金額と数値が結合した語を分ける。"""
    out = []
    for w in words:
        m = GLUED_PAREN.match(w['text'])
        if not m:
            out.append(w)
            continue
        span = w['xMax'] - w['xMin']
        frac = len(m.group(1)) / len(w['text'])
        cut = w['xMin'] + span * frac
        out.append({**w, 'text': m.group(1), 'xMax': cut})
        out.append({**w, 'text': m.group(2), 'xMin': cut})
    return out


def lines(words):
    result = []
    for word in unglue(sorted(words, key=lambda w: (w['yMin'], w['xMin']))):
        if not result or word['yMin'] - result[-1][0]['yMin'] > 5:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w['xMin']) for row in result]


def text_of(words):
    value = ''
    previous = None
    for word in words:
        if previous is not None and word['xMin'] - previous['xMax'] > 1:
            value += ' '
        value += word['text']
        previous = word
    return value or None


def position(page, words):
    return {'物理頁': page, '上端': min(w['yMin'] for w in words),
            '下端': max(w['yMax'] for w in words)}


def num_or_none(text):
    m = re.sub(r'[^0-9-]', '', text) if text else ''
    return int(m) if m and m != '-' else None


def is_amount(token):
    return bool(NUM.match(token))


def numeric(text):
    if text in (None, '－'):
        return None
    return int(re.sub(r'[^0-9-]', '', text))


def segments(words):
    count = 1
    for a, b in zip(words, words[1:]):
        if b['xMin'] - a['xMax'] > 6:
            count += 1
    return count


def kan_values(words):
    """款集計・歳出合計の金額行: 印字順の7セルを固定順序へ割り当てる。"""
    cells = [w['text'] for w in words]
    if len(cells) != 7:
        raise ValueError(f'款集計/歳出合計の金額行が7セルでない: {cells}')
    return dict(zip(KAN_KEYS, cells))


def parse_kou_heading(words, page):
    """項-only見出し行: N項 名称 (予算現額) 決算額 [<前年決算額>]。目を持たない会計用。"""
    if not words:
        return None
    m = KOU_HEADING.match(words[0]['text'])
    if not m or words[0]['xMin'] > 80:
        return None
    try:
        iparen = next(i for i in range(2, len(words)) if PAREN.match(words[i]['text']))
    except StopIteration:
        return None
    if iparen + 1 >= len(words):
        return None
    rest = words[iparen + 1:]
    if not rest or not is_amount(rest[0]['text']):
        return None
    prev_words = rest[1:]
    if prev_words and not PREV_TEXT.match(squashed(prev_words)):
        return None
    name = text_of(words[1:iparen])
    if not name:
        return None
    return {'番号': m.group(1), '名称': name,
            '予算現額': words[iparen]['text'], '当年度決算額': rest[0]['text'],
            '前年度決算額': squashed(prev_words) or None,
            **position(page, words)}


def parse_moku_heading(words, page):
    """項・目の見出し行: N 項名  N 目名  (予算現額)  決算額  [<前年決算額>]。"""
    if not words or not is_amount(words[0]['text']) or words[0]['xMin'] > 80:
        return None
    try:
        split = next(i for i in range(1, len(words)) if is_amount(words[i]['text']))
    except StopIteration:
        return None
    if split == 1 or words[split]['xMin'] > 250:
        return None
    try:
        iparen = next(i for i in range(split + 1, len(words)) if PAREN.match(words[i]['text']))
    except StopIteration:
        return None
    if iparen <= split + 1 or iparen + 1 >= len(words):
        return None
    rest = words[iparen + 1:]
    if not rest or not is_amount(rest[0]['text']):
        return None
    prev_words = rest[1:]
    if prev_words and (not squashed(prev_words) or not PREV_TEXT.match(squashed(prev_words))):
        return None
    return {'項_番号': words[0]['text'], '項_名称': text_of(words[1:split]),
            '項_物理頁': page, '項_上端': min(w['yMin'] for w in words[:split]),
            '項_下端': max(w['yMax'] for w in words[:split]),
            '番号': words[split]['text'], '名称': text_of(words[split + 1:iparen]),
            '予算現額': words[iparen]['text'], '当年度決算額': rest[0]['text'],
            '前年度決算額': squashed(rest[1:]) or None,
            **position(page, words)}


RANGE_MARK = re.compile(r'^[〜～−–—]$')


def parse_moku_pending(words, page):
    """金額行のない項・目見出し行（範囲目含む）。金額は次行で補う。"""
    if not words or not is_amount(words[0]['text']) or words[0]['xMin'] > 80:
        return None
    split = next((i for i in range(1, len(words)) if is_amount(words[i]['text'])), None)
    if split is None or split == 1 or words[split]['xMin'] > 250:
        return None
    if not words[1:split]:
        return None
    tail = words[split + 1:]
    if not tail or any(PAREN.match(w['text']) for w in tail):
        return None
    nums = [w for w in tail if is_amount(w['text'])]
    marks = [w for w in tail if RANGE_MARK.match(w['text'])]
    if len(nums) > 1 or (nums and not marks):
        return None
    name_words = [w for w in tail if w not in nums]
    if not name_words:
        return None
    return {'項_番号': words[0]['text'], '項_名称': text_of(words[1:split]),
            '項_物理頁': page, '項_上端': min(w['yMin'] for w in words[:split]),
            '項_下端': max(w['yMax'] for w in words[:split]),
            '番号': words[split]['text'] + (marks[0]['text'] + nums[0]['text'] if nums else ''),
            '名称': text_of(name_words),
            '物理頁': page, '上端': min(w['yMin'] for w in words),
            '下端': max(w['yMax'] for w in words)}


def parse_moku_amounts(words):
    """項・目見出しの次行: (予算現額) 決算額 [<前年決算額>] のみの行。"""
    if not words or not PAREN.match(words[0]['text']):
        return None
    rest = words[1:]
    if not rest or not is_amount(rest[0]['text']):
        return None
    prev = rest[1:]
    if prev and not PREV_TEXT.match(squashed(prev)):
        return None
    return {'予算現額': words[0]['text'], '当年度決算額': rest[0]['text'],
            '前年度決算額': squashed(prev) or None}


def parse_jigyo_heading(words, page):
    """事業の見出し行: [番号] 名称  担当課  (予算現額)  決算額。"""
    paren = [w for w in words if PAREN.match(w['text']) and 399 <= w['xMin'] < 505]
    decided = [w for w in words if is_amount(w['text']) and 470 <= w['xMin'] and w['xMax'] <= 585]
    if len(paren) != 1 or len(decided) != 1:
        return None
    head = [w for w in words if w['xMax'] <= paren[0]['xMin']]
    if not head:
        return None
    number = None
    if is_amount(head[0]['text']) and head[0]['xMin'] < 70:
        number = head[0]['text']
        head = head[1:]
    segs = []
    for w in head:
        if segs and w['xMin'] - segs[-1][-1]['xMax'] > 6:
            segs.append([])
        if segs:
            segs[-1].append(w)
        else:
            segs.append([w])
    dept_words = []
    while len(segs) >= 2 and DEPT_SUFFIX.search(squashed(segs[-1])):
        dept_words = segs.pop() + dept_words
    name_words = [w for seg in segs for w in seg]
    if not name_words:
        return None
    return {'番号': number, '名称': text_of(name_words),
            '担当課': text_of(dept_words) if dept_words else None,
            '予算現額': paren[0]['text'], '当年度決算額': decided[0]['text'],
            '前年度決算額': None, '説明': None,
            **position(page, words)}


def parse_jigyo_continuation(words):
    """事業見出しの次行: 追加の担当課と <前年度決算額>。"""
    prev = [w for w in words if PREV.match(w['text'])]
    if not prev or not PREV_TEXT.match(squashed(prev)):
        return None
    others = [w for w in words if w not in prev]
    if any(w['xMin'] < 230 for w in others):
        return None
    return {'前年': squashed(prev),
            '課': text_of([w for w in others if w['xMin'] < RIGHT_X]) if others else None,
            'annex': [w for w in others if w['xMin'] >= RIGHT_X]}


RANGE_MARK = re.compile(r'^[〜～−–—]$')
KAN_TITLE_MARK = re.compile(r'事務報告書')
KAN_NUMBER = re.compile(r'^[0-9]{1,2}$')


def parse_kan_heading_fragment(words, page):
    """款見出しの先頭行: 番号+名称（款名が長く次の行へ折り返す会計用）。

    左欄の先頭語が款番号（1-2桁の数字）で、行内に金額がなく、残語に項見出し・
    marker・括弧金額・前年度額・本文（事務報告書）を含まない行だけを保留する。
    事業見出し（(予算現額)を含む）・項/目見出し（先頭が「N項」）・款集計の
    金額行（桁区切り金額を持つ）はこの形にならない。款番号+名称+本文が1行で
    揃う款見出しは従来の単行分支岐が扱うため対象外。
    """
    head = [w for w in words if w['xMin'] < RIGHT_X]
    if not head or not KAN_NUMBER.match(head[0]['text']) or head[0]['xMin'] > 110:
        return None
    if KAN_TITLE_MARK.search(squashed(words)) or len(head) < 2:
        return None
    if any(is_amount(w['text']) for w in words[1:]):
        return None
    if any(KOU_HEADING.match(w['text']) for w in head[1:]):
        return None
    if any(MARKER_ITEM.match(w['text']) or MARKER_SUB.match(w['text'])
           or PAREN.match(w['text']) or PREV.match(w['text']) for w in head[1:]):
        return None
    name = ''.join(w['text'] for w in head[1:])
    if not name:
        return None
    return {'番号': head[0]['text'], '名称': name, 'held': [(page, words)],
            'title': False, **position(page, head)}


def kan_name_fragment(words):
    """款見出しの名称断片。左欄の款名列（xMax 250 以下）に印字され、
    金額・括弧金額・前年度額・marker・項見出し・本文を含まない行だけを断片とする。
    款集計のラベル行（決算額・資金分解・執行率）は左欄全域に広がるため対象外。
    """
    head = [w for w in words if w['xMin'] < RIGHT_X]
    if not head or any(w['xMax'] > 250 for w in head):
        return None
    if KAN_TITLE_MARK.search(squashed(words)):
        return None
    if any(KOU_HEADING.match(w['text']) or MARKER_ITEM.match(w['text'])
           or MARKER_SUB.match(w['text']) or PAREN.match(w['text'])
           or PREV.match(w['text']) or is_amount(w['text']) for w in head):
        return None
    return ' '.join(w['text'] for w in head) or None


class Builder:
    def __init__(self):
        self.detail = []
        self.funding = []
        self.annex = []
        self.obs_kan, self.obs_kou, self.obs_moku, self.obs_jigyo, self.obs_total = [], [], [], [], []
        self.kan_amount_cells = []
        self.kan = self.kou = self.moku = self.jigyo = None
        self.item = None          # open （n）内訳項目
        self.pending_sub = None   # 金額行待ちの細目
        self.pending_funding = None
        self.pending_moku = None  # 金額行待ちの項・目見出し
        self.pending_kan = None   # 款見出しの保留行（番号+名称・続き行に本文が折り返す会計）
        self.kan_rejected = set()   # 款見出しとして成立しなかった保留行（再捕捉しない）
        self.after_total = False
        self.detail_cols = None   # 明細表の列（funds 解決後に設定）
        self.in_table = False     # 内表（実績・収支・区分表）領域内か
        self.in_named_table = False  # 表題付き内表の領域内か。marker行を annex へ送る
        self.declared_stats = False  # options stat_titles ありのときのみ表題機構を使う
        self.pending_leaf = None  # 「名称行+金額行」wrap型leafの名称行待ち
        self.right_extra = []  # marker/sub行の中段付随fundラベル。次right_lineへ渡す

    def path_cols(self, allowed=None):
        out = {}
        if self.kan:
            out['款_番号'] = self.kan['番号']
        # 款直轄事業 (_kodirect) の配下では項を継承しない。
        kodirect = self.jigyo is not None and self.jigyo.get('_kodirect')
        if self.kou and not kodirect:
            out['項_番号'] = self.kou['番号']
        if self.moku:
            out['目_番号'] = self.moku['番号']
        if self.jigyo:
            out['事業_番号'] = self.jigyo['番号']
            out['事業_物理頁'] = self.jigyo['物理頁']
            out['事業_上端'] = self.jigyo['上端']
        return out

    def emit_leaf(self, sub=None):
        row = {k: None for k in (self.detail_cols or DETAIL_COLUMNS)}
        if self.kan:
            row.update({'款_' + k: v for k, v in self.kan.items()})
        kodirect = self.jigyo is not None and self.jigyo.get('_kodirect')
        if self.kou and not kodirect:
            row.update({'項_' + k: v for k, v in self.kou.items() if not k.startswith('_')})
        if self.moku:
            row.update({'目_' + k: v for k, v in self.moku.items()})
        if self.jigyo:
            row.update({'事業_' + k: v for k, v in self.jigyo.items() if not k.startswith('_')})
        if self.item:
            row.update({'内訳_' + k: v for k, v in self.item.items() if not k.startswith('_')})
        if sub:
            row.update({'細目_番号': sub.get('番号'), '細目_名称': sub.get('名称'),
                        '細目_数量': sub.get('数量'), '細目_金額': sub.get('金額'),
                        '細目_物理頁': sub['物理頁'], '細目_上端': sub['上端'],
                        '細目_下端': sub['下端']})
        if self.jigyo:
            self.jigyo['_leaf'] = True
        if self.item:
            self.item['_leaf'] = True
        self.detail.append(row)

    def flush_sub(self):
        if self.pending_sub:
            name = self.pending_sub['名称'] or ''
            if (re.search(r'(^|\s)[\d,]+(\s|$)', name)
                    or FUNDING_ECHO.match(name.replace(' ', ''))):
                self.emit_annex(self.pending_sub['物理頁'], self.pending_sub['words'])
            else:
                self.emit_leaf(self.pending_sub)
            self.pending_sub = None

    def close_item(self):
        self.flush_sub()
        if self.item and not self.item.get('_leaf'):
            self.emit_leaf()            # 内訳項目自身が葉
        self.item = None

    def close_jigyo(self):
        self.close_item()
        if self.pending_leaf:
            self.emit_annex(self.pending_leaf['物理頁'], self.pending_leaf['words'])
            self.pending_leaf = None
        self.flush_funding()
        self.in_table = False
        self.in_named_table = False
        if self.jigyo and not self.jigyo.get('_leaf'):
            self.emit_leaf()            # 内訳なし事業自身が葉
        self.jigyo = None

    def flush_funding(self):
        if self.pending_funding:
            self.emit_annex(self.pending_funding['page'], self.pending_funding['words'])
            self.pending_funding = None

    def emit_annex(self, page, words):
        if not words:
            return
        row = {k: None for k in ANNEX_COLUMNS}
        row.update(self.path_cols())
        row.update({'本文': text_of(words), '物理頁': page,
                    '上端': min(w['yMin'] for w in words),
                    '下端': max(w['yMax'] for w in words),
                    '左端': min(w['xMin'] for w in words),
                    '右端': max(w['xMax'] for w in words)})
        self.annex.append(row)

    def emit_funding(self, page, label_words, amount_word):
        row = {k: None for k in FUNDING_COLUMNS}
        row.update(self.path_cols())
        row.update({'財源_名称': text_of(label_words), '財源_金額': amount_word['text'],
                    '財源_物理頁': page,
                    '財源_上端': min(w['yMin'] for w in label_words),
                    '財源_下端': max(max(w['yMax'] for w in label_words), amount_word['yMax'])})
        self.funding.append(row)

    def table_viable(self, words):
        """表領域内の行を通常経路へ通すか。keep対象から外す判定用。
        (n)/アイウで始まる行は marker 側の判断へ委ね、pending を完成させる
        金額行も通す。それ以外（かな断片・グリッド行）は表内に保つ。"""
        first = words[0]['text']
        if _MARKER_LEAD.match(first):
            return True
        if (len(words) == 1 and AMOUNT_FULL.match(first)
                and (self.pending_leaf is not None or self.pending_sub is not None
                     or (self.item is not None and self.item.get('金額') is None))):
            return True
        return False

    def split_trailing(self, body):
        """marker/sub行末尾の付随トークンを分離する。(PREV・fundラベル・in-band金額)
        末尾が PREV または fundラベル1語で、その直前が in-band 金額のときだけ分離する。
        それ以外は旧経路と同一（末尾が in-band 金額なら金額、そうでなければ付随なし）。"""
        rest = list(body)
        if len(rest) == 1 and PREV_TEXT.match(rest[-1]['text']):
            return [], None, rest[0], []
        if (len(rest) >= 2
                and (PREV_TEXT.match(rest[-1]['text'])
                     or (len(rest[-1]['text']) >= 2 and FUND_LABEL.search(rest[-1]['text'])
                         and not FUND_DENY.search(rest[-1]['text'])))
                and AMOUNT_FULL.match(rest[-2]['text'])
                and AMOUNT_BAND[0] <= rest[-2]['xMax'] <= AMOUNT_BAND[1] + 8):
            tail = rest.pop()
            prev = tail if PREV_TEXT.match(tail['text']) else None
            funds = [] if prev is not None else [tail]
            return rest[:-1], rest[-1]['text'], prev, funds
        amount = None
        if rest and AMOUNT_FULL.match(rest[-1]['text']) \
                and AMOUNT_BAND[0] <= rest[-1]['xMax'] <= AMOUNT_BAND[1] + 8:
            amount = rest.pop()['text']
        return rest, amount, None, []

    def pop_right_extra(self):
        extra, self.right_extra = self.right_extra, []
        return extra

    def left_line(self, words, page):
        """左欄(x<405)の1行を振り分ける。行を消費したら True。"""
        if not words:
            return False
        first = words[0]
        # wrap型leafの金額行待ち: 直前の名称行と金額行を結合する
        if self.pending_leaf is not None:
            if (len(words) == 1 and AMOUNT_FULL.match(first['text'])
                    and AMOUNT_BAND[0] <= first['xMax'] <= AMOUNT_BAND[1] + 8
                    and self.leaf_within_parent(num_or_none(first['text']))):
                pl = self.pending_leaf
                self.pending_leaf = None
                self.emit_leaf({'番号': None, '名称': pl['名称'], '数量': None,
                                '金額': first['text'], '物理頁': pl['物理頁'],
                                '上端': pl['上端'], '下端': first['yMax']})
                return True
            self.emit_annex(self.pending_leaf['物理頁'], self.pending_leaf['words'])
            self.pending_leaf = None
        marker = MARKER_ITEM.match(first['text'])
        if marker and first['xMin'] < 110 and self.jigyo is not None \
                and not re.search(r'^・|[、。]$', first['text'][marker.end():]):
            body = words[1:]
            body, amount, prev, funds = self.split_trailing(body)
            # 表題付き内表内の金額なし (n) 行は統計表の断片として annex へ送り、表状態を保つ。
            # 金額あり行は従来どおり内訳として消費する (一般会計の正規 (n) と区別するため)。
            # 未宣言（一般会計）では named が立たないため出力不変。
            if amount is None and self.in_named_table and self.declared_stats:
                return False
            self.in_table = False
            self.close_item()
            parent = num_or_none(self.jigyo['当年度決算額'])
            if amount is not None and parent is not None \
                    and num_or_none(amount) > parent:
                return False
            if prev is not None:
                if self.jigyo['前年度決算額'] is None:
                    self.jigyo['前年度決算額'] = prev['text']
                else:
                    self.emit_annex(page, [prev])
            if funds:
                self.right_extra.extend(funds)
            head = first['text'][marker.end():] or None
            name = ' '.join(t for t in [head, text_of(body)] if t)
            self.item = {'番号': marker.group(0), '名称': name or None,
                         '金額': amount, **position(page, words)}
            return True
        sub = MARKER_SUB.match(first['text'])
        if (sub and first['xMin'] < 120 and self.item is not None
                and len(words) > 1 and len(words[1]['text']) >= 2):
            body = words[1:]
            body, amount, prev, funds = self.split_trailing(body)
            count = None
            if amount is not None and not self.leaf_within_parent(num_or_none(amount)):
                body, amount, prev, funds = list(words[1:]), None, None, []
            if prev is not None:
                if self.jigyo['前年度決算額'] is None:
                    self.jigyo['前年度決算額'] = prev['text']
                else:
                    self.emit_annex(page, [prev])
            if funds:
                self.right_extra.extend(funds)
            if body and (COUNT_WORD.match(body[-1]['text'])
                         or re.match(r'^\d{1,4}$', body[-1]['text'])):
                count = body.pop()['text']
            self.in_table = False
            self.flush_sub()
            self.pending_sub = {'番号': first['text'], '名称': text_of(body),
                                '数量': count, '金額': amount, 'words': words,
                                **position(page, words)}
            if amount is not None:
                self.flush_sub()
            return True
        # 内表領域内は全行を構造対象から外す。領域はひらがなを含む散文行
        # （文節・助詞を持つ文）または40字超の非表行で終了し、
        # 短い行（縦書きラベル・区分名・節タイトルの折り返し等）は領域内とみなす
        if self.in_table:
            txt = squashed(words)
            # 宣言統計表の領域内では、構造化の可能性がない短行だけ表内に保つ
            # （かな断片での早期終了を防ぐ）。wrap候補・金額行・番号なし候補は
            # 通常経路へ通す。未宣言（一般会計）は従来どおりで出力不変。
            if (self.in_named_table and self.declared_stats and len(txt) <= 40
                    and not self.table_viable(words)):
                return False
            if (table_like(words)
                    or (len(re.findall(r'[ぁ-ん]', txt)) < 2 and len(txt) <= 40)):
                return False
            self.in_table = False
            self.in_named_table = False
        # 金額だけの行: 継続中の細目または内訳項目の金額を閉じる
        if (len(words) == 1 and AMOUNT_FULL.match(first['text'])
                and AMOUNT_BAND[0] <= first['xMax'] <= AMOUNT_BAND[1] + 8):
            if self.pending_sub and self.pending_sub['金額'] is None:
                self.pending_sub['金額'] = first['text']
                self.pending_sub['下端'] = max(self.pending_sub['下端'], first['yMax'])
                self.flush_sub()
                return True
            if self.item is not None and self.item['金額'] is None:
                self.item['金額'] = first['text']
                self.item['下端'] = max(self.item['下端'], first['yMax'])
                return True
        # 番号なし内訳行: 「名称 … 金額」2片行と「名称 … 数量 金額」3片行。
        # 統計・内部収支表（区分…件数/人数/回数の実績列）の混入を防ぐため、
        # 金額はカンマ桁区切りで10,000以上、数量語は単位・括弧を伴う形に限定し、
        # 名称側に数値トークンを含まず、金額は親の印字額以下に限る。
        if self.jigyo is not None and len(words) >= 2:
            segs = segments(words)
            last = num_or_none(words[-1]['text']) if AMOUNT_FULL.match(words[-1]['text']) else None
            if segs in (2, 3) and last is not None and last >= 10000 \
                    and AMOUNT_BAND[0] <= words[-1]['xMax'] <= AMOUNT_BAND[1] + 8:
                qty = None
                names = words[:-1]
                if segs == 3:
                    mid = words[-2]['text']
                    if not re.match(r'^[0-9,]+[^\d,\s]', mid):
                        return False
                    qty = mid
                    names = words[:-2]
                name_text = text_of(names)
                if (names and not LEAF_DENY.search(squashed(names))
                        and not FUNDING_ECHO.match(squashed(names))
                        and not any(is_amount(w['text']) or PAREN.match(w['text'])
                                    or re.match(r'^[\d,（()）<>＜＞〜～\-－]+$', w['text'])
                                    for w in names)
                        and self.leaf_within_parent(last)):
                    self.flush_sub()
                    self.emit_leaf({'番号': None, '名称': name_text, '数量': qty,
                                    '金額': words[-1]['text'], **position(page, words)})
                    return True
        # wrap型leafの名称行候補（金額が次行に折り返す形）。
        # 文末記号・ひらがな終わり（散文折り返し）は候補から外す
        if (self.jigyo is not None and len(words) == 1
                and not is_amount(first['text'])
                and 2 <= len(first['text']) <= 40
                and not re.search(r'[。、※【]|ぁ-ん$', first['text'])
                and not LEAF_DENY.search(first['text'])):
            self.pending_leaf = {'名称': first['text'], 'words': words,
                                 **position(page, words)}
            return True
        return False

    def leaf_within_parent(self, amount):
        if amount is None:
            return True
        parent = None
        if self.item is not None and self.item['金額'] is not None:
            parent = num_or_none(self.item['金額'])
        if parent is None and self.jigyo is not None:
            parent = num_or_none(self.jigyo['当年度決算額'])
        return parent is None or amount <= parent

    def right_line(self, words, page):
        """右欄(x>=405)の財源内訳行。未所属は annex へ。

        財源の金額は右端(xMax≈560-568)へ右寄せ。右欄に入り込んだ内表の
        断片（右端が揃わない金額・財源名でないラベル）は annex へ送る。
        折り返しラベルの結合は60pt以内の近接行に限る。
        """
        if not words:
            return
        if self.jigyo is None:
            self.emit_annex(page, words)
            return
        famounts = [w for w in words if is_amount(w['text']) and 545 <= w['xMax'] <= 585]
        others = [w for w in words if w not in famounts]
        if (self.pending_funding
                and words[0]['yMin'] - self.pending_funding['y0'] > 60):
            self.emit_annex(self.pending_funding['page'], self.pending_funding['words'])
            self.pending_funding = None
        if famounts and not others and self.pending_funding:
            prev = self.pending_funding
            self.pending_funding = None
            row = {k: None for k in FUNDING_COLUMNS}
            row.update(self.path_cols())
            row.update({'財源_名称': text_of(prev['words']),
                        '財源_金額': famounts[-1]['text'], '財源_物理頁': prev['page'],
                        '財源_上端': min(w['yMin'] for w in prev['words']),
                        '財源_下端': famounts[-1]['yMax']})
            self.funding.append(row)
            return
        label_text = squashed(others)
        fund_like = len(label_text) >= 2 and FUND_LABEL.search(label_text) and not FUND_DENY.search(label_text)
        if not famounts and fund_like:
            if self.pending_funding:
                self.pending_funding['words'] += others
            else:
                self.pending_funding = {'words': others, 'page': page,
                                        'y0': min(w['yMin'] for w in others)}
            return
        if famounts and others and fund_like:
            if self.pending_funding:
                prev = self.pending_funding
                label_words = prev['words'] + others
                self.pending_funding = None
                row = {k: None for k in FUNDING_COLUMNS}
                row.update(self.path_cols())
                row.update({'財源_名称': (text_of(prev['words']) or '') + '\n' + (text_of(others) or ''),
                            '財源_金額': famounts[-1]['text'], '財源_物理頁': prev['page'],
                            '財源_上端': min(w['yMin'] for w in label_words),
                            '財源_下端': max(max(w['yMax'] for w in label_words),
                                           famounts[-1]['yMax'])})
                self.funding.append(row)
            else:
                self.emit_funding(page, others, famounts[-1])
            return
        self.emit_annex(page, words)


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Hachioji general settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '132012'
            or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf'
            or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Hachioji text settlement expenditure only')
    account = options.get('account', '一般会計')
    funds = options.get('fund_columns') or [n for n in DEFAULT_FUNDS]
    if len(funds) != 5 or any(not isinstance(n, str) or not n for n in funds):
        raise ValueError('fund_columns must be 5 printed fund names')
    stat_titles = options.get('stat_titles') or []
    if any(not isinstance(t, str) or not t for t in stat_titles):
        raise ValueError('stat_titles must be non-empty strings')
    kan_keys = ['決算額'] + funds + ['執行率']
    selected = sorted({p for scope in source['scope'] if scope['account'] == account
                for first, last in scope['pages'] for p in range(first, last + 1)})
    if not selected:
        raise ValueError(f'Measured scope for {account} is empty')
    runs = []
    start = prev = selected[0]
    for p in selected[1:]:
        if p == prev + 1:
            prev = p
        else:
            runs.append((start, prev))
            start = prev = p
    runs.append((start, prev))
    destination = Path(destination)
    observations = destination / 'hachioji-observations'
    observations.mkdir(parents=True, exist_ok=True)
    pages = []
    for first, last in runs:
        # 連続1区間では従来と同一の観測path・同一出力にする。非連続ではgap頁をskipする。
        name = 'pages-bbox.html' if len(runs) == 1 else f'pages-bbox-{first}-{last}.html'
        pages.extend(observe(source['path'], first, last, observations / name))

    b = Builder()
    b.detail_cols = detail_columns(funds)
    b.declared_stats = bool(stat_titles)
    label_state = None          # None | 'kan'（款見出し済み・集計行待ち）| 'total'
    for page, words in pages:
        b.flush_funding()
        # 行は1行ずつ処理する。款見出しの保留を解除するとき、保留行を元の順序で
        # Stream の先頭へ戻して通常経路を通し直す（不発時の出力は従来と同一）。
        stream = deque((page, line) for line in lines(words))
        while stream:
            page, line = stream.popleft()
            y = line[0]['yMin']
            flat = squashed(line)
            if y > FOOTER_TOP:
                b.emit_annex(page, line)
                continue
            # 宣言された統計表の表題: wrap候補に吸われても表状態を立てる。
            # 一般会計のoptionsには宣言がないため既存出力に影響しない。
            if b.jigyo is not None and any(t in flat for t in stat_titles):
                b.in_table = True
                b.in_named_table = True
            # 款見出しが複数行に折り返す会計（款名が長く番号+名称と本文が別行になる場合）。
            # 先頭行を保留し、本文（事務報告書）・名称断片を経て款見出しとして確定する。
            # 款見出しとして確定できないと判明した行は、保留行もまとめて元の順序の
            # まま通常経路へ戻すため、不発時の出力は従来と完全に同一になる。款名の
            # 印字結合結果だけをrawへ載せ、観測列は増やさない。
            if b.pending_kan is not None:
                pk = b.pending_kan
                if KAN_TITLE_MARK.search(flat):
                    if not pk['title']:
                        pk['title'] = True
                        head = [w for w in line if w['xMin'] < 115 and not is_amount(w['text'])]
                        if head:
                            pk['名称'] = pk['名称'] + ''.join(w['text'] for w in head)
                    pk['held'].append((page, line))
                    continue
                if pk['title'] and (frag := kan_name_fragment(line)) is not None:
                    pk['名称'] = pk['名称'] + frag
                    pk['held'].append((page, line))
                    continue
                if pk['title'] and len(pk['held']) > 1:
                    # 名称断片が終わり、款見出しとして確定する。確定後はこの行を
                    # 通常経路へ通す（款集計のラベル行・金額行は既存の状態機械が扱う）。
                    b.close_jigyo()
                    for held_page, held_line in pk['held']:
                        b.emit_annex(held_page, held_line)
                    b.kan = {'番号': pk['番号'], '名称': pk['名称'],
                             **{k: None for k in kan_keys},
                             '物理頁': pk['物理頁'], '上端': pk['上端'], '下端': pk['下端']}
                    b.kou = b.moku = None
                    b.kan_amount_cells = []
                    label_state = 'kan'
                    b.pending_kan = None
                else:
                    # 款見出しとして成立しなかった。保留行とこの行を元の順序で
                    # 通常経路へ戻す。戻した保留行は再捕捉しない。
                    items = pk['held'] + [(page, line)]
                    b.pending_kan = None
                    for held_page, held_line in pk['held']:
                        b.kan_rejected.add((held_page, held_line[0]['yMin'], held_line[0]['xMin']))
                    for item in reversed(items):
                        stream.appendleft(item)
                    continue
            if (fragment := parse_kan_heading_fragment(line, page)) is not None \
                    and (page, line[0]['yMin'], line[0]['xMin']) not in b.kan_rejected:
                b.pending_kan = fragment
                continue
            # 款の見出しブロック（頁上部の書名行 → 7分割ラベル行 → 金額行）。
            # 頁途中に款が開く会計もあるためy位置では限定しない（一般会計の頁途中該当は0件）。
            if '事務報告書' in flat and line[0]['xMin'] < 70:
                b.close_jigyo()
                head = [w for w in line if w['xMin'] < 115]
                if head and is_amount(head[0]['text']):
                    name = ''
                    for w in head[1:]:
                        if w['text'] == '主':
                            break
                        name += w['text']
                    b.kan = {'番号': head[0]['text'], '名称': name or text_of(head[1:]),
                             **{k: None for k in kan_keys}, **position(page, head)}
                    b.kou = b.moku = None
                    b.kan_amount_cells = []
                    label_state = 'kan'
                b.emit_annex(page, line)
                continue
            if label_state == 'kan' and '執行率' in flat:
                label_state = 'kan_amounts'
                b.emit_annex(page, line)
                continue
            if label_state == 'kan_amounts':
                # 款集計の金額行: 7セルを右端 (xMax) 順に固定順序へ割り当てる。
                # 頁途中の款見出しではy jitterで行が割れるためxMax順で復元する。
                # 単一行では従来の印字順と同一になる。
                b.kan_amount_cells.extend((w['xMax'], w['text']) for w in line)
                if len(b.kan_amount_cells) > 7:
                    raise ValueError(f'款集計の金額セルが7超: {[t for _, t in b.kan_amount_cells]}')
                if len(b.kan_amount_cells) == 7:
                    vals = dict(zip(kan_keys, [t for _, t in sorted(b.kan_amount_cells)]))
                    b.kan.update(vals)
                    b.obs_kan.append({'page': page, '番号': b.kan['番号'], '名称': b.kan['名称'],
                                      **vals, **position(page, line)})
                    b.kan_amount_cells = []
                    label_state = None
                b.emit_annex(page, line)
                continue
            if '歳出合計' in flat and len(line) <= 6 and y < 140:
                b.close_jigyo()
                b.kan = b.kou = b.moku = None
                b.after_total = True
                label_state = 'total_labels'
                b.emit_annex(page, line)
                continue
            # 給与費決算明細書の開始: 開いている事業を閉じる。以降の行は通常経路で
            # 処理する (歳出合計後の給与域と同一の見出しなし状態になるため annex へ送られる)。
            # 状態リセットのみで行自体は消費しないため、一般会計の出力は変わらない。
            if '給与費決算明細書' in flat and y < 140:
                b.close_jigyo()
                b.kan = b.kou = b.moku = None
                b.kan_amount_cells = []
                label_state = None
            if label_state == 'total_labels':
                if '執行率' in flat:
                    b.emit_annex(page, line)
                    continue
                label_state = 'total_amounts'
            if label_state == 'total_amounts':
                b.obs_total.append({'page': page, **kan_values(line), **position(page, line)})
                label_state = None
                b.emit_annex(page, line)
                continue
            if b.pending_moku is not None:
                if (all(w['xMax'] < 450 for w in line)
                        and (amts := parse_moku_amounts(line))):
                    pm = b.pending_moku
                    b.pending_moku = None
                    pm.pop('words')
                    b.close_jigyo()
                    b.kou = {'番号': pm.pop('項_番号'), '名称': pm.pop('項_名称'),
                             '物理頁': pm.pop('項_物理頁'), '上端': pm.pop('項_上端'),
                             '下端': pm.pop('項_下端')}
                    pm.update(amts)
                    b.moku = pm
                    b.obs_moku.append({'page': pm['物理頁'], '款': b.kan and b.kan['番号'],
                                       '項': b.kou['番号'], '目': pm['番号'], '名称': pm['名称'],
                                       '予算現額': pm['予算現額'], '当年度決算額': pm['当年度決算額'],
                                       '前年度決算額': pm['前年度決算額']})
                    continue
                b.emit_annex(b.pending_moku['物理頁'], b.pending_moku['words'])
                b.pending_moku = None
            moku = parse_moku_heading(line, page)
            if moku:
                b.close_jigyo()
                b.kou = {'番号': moku.pop('項_番号'), '名称': moku.pop('項_名称'),
                         '物理頁': moku.pop('項_物理頁'), '上端': moku.pop('項_上端'),
                         '下端': moku.pop('項_下端')}
                b.moku = moku
                b.obs_moku.append({'page': page, '款': b.kan and b.kan['番号'],
                                   '項': b.kou['番号'], '目': moku['番号'], '名称': moku['名称'],
                                   '予算現額': moku['予算現額'], '当年度決算額': moku['当年度決算額'],
                                   '前年度決算額': moku['前年度決算額']})
                continue
            pending = parse_moku_pending(line, page)
            if pending:
                pending['words'] = line
                b.pending_moku = pending
                continue
            kou = parse_kou_heading(line, page)
            if kou:
                b.close_jigyo()
                b.kou = {'番号': kou['番号'], '名称': kou['名称'], '物理頁': kou['物理頁'],
                         '上端': kou['上端'], '下端': kou['下端'],
                         '_予算現額': kou['予算現額'], '_当年度決算額': kou['当年度決算額'],
                         '_前年度決算額': kou['前年度決算額']}
                b.moku = None
                b.obs_kou.append({'page': page, '款': b.kan and b.kan['番号'],
                                   '項': kou['番号'], '名称': kou['名称'],
                                   '予算現額': kou['予算現額'],
                                   '当年度決算額': kou['当年度決算額'],
                                   '前年度決算額': kou['前年度決算額']})
                continue
            jigyo = parse_jigyo_heading(line, page)
            if jigyo:
                b.close_jigyo()
                # 款直轄事業: 事業決算が現項決算を上回り (containment違反)、
                # かつ款決算と一致するときのみ項を継承しない。決算どうしで比べる。
                if (b.kou is not None and b.kan is not None and b.kan.get('決算額') is not None
                        and (nd := num_or_none(jigyo['当年度決算額'])) is not None
                        and (td := num_or_none(b.kou.get('_当年度決算額'))) is not None
                        and (kd := num_or_none(b.kan['決算額'])) is not None
                        and nd > td and nd == kd):
                    jigyo['_kodirect'] = True
                b.jigyo = jigyo
                b.obs_jigyo.append({'page': page, '款': b.kan and b.kan['番号'],
                                    '項': b.kou and b.kou['番号'], '目': b.moku and b.moku['番号'],
                                    '番号': jigyo['番号'], '名称': jigyo['名称'],
                                    '担当課': jigyo['担当課'], '予算現額': jigyo['予算現額'],
                                    '当年度決算額': jigyo['当年度決算額']})
                continue
            cont = parse_jigyo_continuation(line)
            if cont and b.jigyo is not None and b.jigyo['前年度決算額'] is None and b.item is None:
                b.jigyo['前年度決算額'] = cont['前年']
                if cont['課']:
                    b.jigyo['担当課'] = (b.jigyo['担当課'] + '\n' + cont['課']
                                       if b.jigyo['担当課'] else cont['課'])
                if cont['annex']:
                    b.emit_annex(page, cont['annex'])
                continue
            left = [w for w in line if w['xMin'] < RIGHT_X]
            if b.left_line(left, page):
                b.right_line(b.pop_right_extra() + [w for w in line if w['xMin'] >= RIGHT_X], page)
                continue
            if (left and segments(left) == 1 and b.jigyo is not None
                    and b.item is None and not b.in_table
                    and not TABLE_TITLE_TAIL.search(squashed(left))):
                text = text_of(left)
                b.jigyo['説明'] = (b.jigyo['説明'] + '\n' + text) if b.jigyo['説明'] else text
            elif left:
                b.emit_annex(page, left)
                if table_start(left):
                    b.in_table = True
                    if b.declared_stats and len(squashed(left)) <= 40 and TABLE_TITLE_TAIL.search(squashed(left)):
                        b.in_named_table = True
            b.right_line([w for w in line if w['xMin'] >= RIGHT_X], page)
    b.close_jigyo()

    (observations / 'observations.json').write_text(json.dumps(
        {'款集計': b.obs_kan, '項見出し': b.obs_kou, '目見出し': b.obs_moku, '事業見出し': b.obs_jigyo,
         '歳出合計': b.obs_total}, ensure_ascii=False, indent=2) + '\n')

    def cols(names):
        return tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁')
                     else 'DOUBLE' if k.endswith(('上端', '下端', '左端', '右端'))
                     else 'VARCHAR') for k in names)

    outputs = {}
    context = lambda tid: ConversionContext(source['sha256'], tid, __file__)
    # 単表emitのopt-in分離 (131156先例と同型)。省略時は全3表で従来どおり。
    emit = options.get('emit') or ('detail', 'funding', 'annex')
    if any(k not in ('detail', 'funding', 'annex') for k in emit):
        raise ValueError(f'Unknown emit kinds: {emit}')
    if 'detail' in emit:
        if not options.get('detail_table_id'):
            raise ValueError('emit detail requires detail_table_id')
        outputs[options['detail_table_id']] = {
            'path': Path(write_conversion(destination / (options['detail_table_id'] + '.parquet'),
                         b.detail, columns=cols(b.detail_cols),
                         context=context(options['detail_table_id'])).path),
            'metadata': detail_metadata(b.detail_cols, funds, options.get('scope_label'),
                                        options.get('stat_titles'))}
    if 'funding' in emit:
        if not options.get('funding_table_id'):
            raise ValueError('emit funding requires funding_table_id')
        outputs[options['funding_table_id']] = {
            'path': Path(write_conversion(destination / (options['funding_table_id'] + '.parquet'),
                         b.funding, columns=cols(FUNDING_COLUMNS),
                         context=context(options['funding_table_id'])).path),
            'metadata': {'units': [{'text': '円', 'scope': {'kind': 'columns',
                             'columns': ['財源_金額']}}],
                         'notes': [{'text': '事業ブロック右欄の財源内訳。事業の当年度決算額の独立した印字分解であり、'
                                    'detail表の葉金額とは別の軸。ラベルが行またぎの場合は改行で保持。',
                                    'scope': {'kind': 'table'}}],
                         'column_contexts': [{'columns': FUNDING_COLUMNS[:7],
                                              'header_path': ['事業', '財源内訳'],
                                              'grain_columns': ['事業_物理頁', '事業_上端', '財源_上端']}]}}
    if 'annex' in emit:
        if not options.get('annex_table_id'):
            raise ValueError('emit annex requires annex_table_id')
        outputs[options['annex_table_id']] = {
            'path': Path(write_conversion(destination / (options['annex_table_id'] + '.parquet'),
                     b.annex, columns=cols(ANNEX_COLUMNS),
                     context=context(options['annex_table_id'])).path),
            'metadata': {'notes': [{'text': '歳出明細以外の全印字行（頁見出し・款集計行・説明以外の注記・'
                                    '内表・歳出合計・決算総括・給与費決算明細・頁脚）。1印字行=1行で原文保持。'
                                    '款_〜事業_列は行が属する見出しの原典座標。', 'scope': {'kind': 'table'}}],
                         'column_contexts': [{'columns': ['本文', '物理頁', '上端', '下端', '左端', '右端'],
                                              'header_path': ['印字行'],
                                              'grain_columns': ['物理頁', '上端']}]}}
    return outputs


def detail_metadata(columns, funds, scope_label=None, stat_titles=None):
    amounts = [c for c in columns if c.endswith(('決算額', '予算現額', '前年度決算額',
               '金額')) or c in ('款_国庫支出金', '款_都支出金', '款_市債', '款_その他', '款_一般財源',
               '款_保険料', '款_一般会計繰入金')]
    contexts = [{'columns': [c for c in columns if c.startswith(level + '_')],
                 'header_path': ['科目', level] if level != '事業' else ['事業', level],
                 'grain_columns': [level + '_物理頁', level + '_上端']}
                for level in ('款', '項', '目', '事業')]
    contexts.append({'columns': [c for c in columns if c.startswith(('内訳_', '細目_'))],
                     'header_path': ['内訳', '細目'],
                     'grain_columns': ['細目_物理頁', '細目_上端']})
    note = ('「主要な施策の成果・事務報告書」の歳出部（' + (scope_label or '物理148-464頁') + '）。'
            '行は最細の印字金額明細: 事業が（n）内訳項目＋アイウ細目を持てば細目行、'
            '内訳項目のみなら内訳行、内訳のない事業は事業行が葉。'
            '款・項・目・事業・内訳の名称・印字金額・位置を葉行へ反復する。'
            '項は独立した金額行を持たず、見出し行の金額3列は目の値。'
            '款_決算額等7列は款の先頭頁の集計行（単位 円、執行率は％）。'
            '事業の財源内訳は別表 funding、内表・歳出合計・決算総括・給与費決算明細は別表 annex。'
            '本資料は主要施策の抜粋であり、目→事業・款→目の合計検算は原則不成立。'
            '（予算現額）・<前年度決算額>は括弧・不等号を含む印字通りの文字列。')
    if funds != DEFAULT_FUNDS:
        note += ('款の資金分解5列は原典款見出しの印字どおり（' + '・'.join(funds) + '）で、'
                 '一般会計の分解（国庫支出金・都支出金・市債・その他・一般財源）とは列名が異なる。'
                 '決算額・執行率と合わせた7列が款集計行に対応する。')
    if stat_titles:
        note += ('宣言された統計表（' + '・'.join(stat_titles) + '）の (n) 行は表断片として '
                 'annex へ送り、属する事業行を葉とする。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}
