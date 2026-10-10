"""Assemble Suginami's printed settlement spread columns from Poppler word boxes.

One physical A3 landscape page holds one left/right facing pair. The left
printed page carries subject (款/項/目) names and five budget columns; the
right printed page carries the statutory 節 breakdown, three executed
columns (支出済額・翌年度繰越額・不用額) and a 備考 column whose ruled cells
contain either free remarks or hierarchical expenditure breakdowns
(○事業【所管】 → numbered 項目 → numbered 細目, each with a printed amount).
Table rules are detected from grayscale page rasters because this PDF/X
rasterizes under pdftocairo -svg.
"""

import re
import subprocess
from pathlib import Path
import json
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

PAGE_WIDTH, PAGE_HEIGHT = 1190.61, 841.904
BODY_TOP, BODY_BOTTOM = 140, 782
NOTE_LEFT, NOTE_RIGHT = 975, 1172
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
EXECUTED = ['支出済額', '翌年度繰越額', '不用額']
# Left printed page: subject columns then five budget amount bands.
SUBJ_BANDS = [(195, 295), (295, 368), (368, 433), (433, 497), (497, 568)]
# Right printed page: 節区分 number/name, then four amount bands.
SETSU_NUM = (612, 641.5)
SETSU_NAME = (640, 705)
SETSU_BANDS = [(705, 775), (775, 843), (843, 910), (910, 980)]
EXEC_BANDS = SETSU_BANDS[1:]
NOTE_AMOUNT_LEFT = 1090
AMOUNT = re.compile(r'[△]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)')
NUMBER = re.compile(r'[0-9]+')
GLYPH_FIX = {'•': '△', '゜': '0'}
DIGIT_FIX = {'O': '0', 'o': '0', 'l': '1', 'I': '1', '|': '1'}


def normalize(token):
    """Restore printed glyphs mangled by this PDF's font encoding."""
    return GLYPH_FIX.get(token, token)


# --- Text-layer misencoding repair -----------------------------------------
# This PDF was re-encoded in a way that maps several printed glyphs to wrong
# Unicode codepoints (e.g. printed 費 extracts as 脅/贄/背/晋/菩). The rules
# below restore the printed character; each entry was verified against every
# occurrence of the misread character in this document's text layer so the
# misread glyph never appears where it is the true reading (injectivity).
# Rule hits are recorded into observations/repairs.json as evidence.
REPAIR_CHARS = {
    '脅': '費', '贄': '費', '背': '費', '晋': '費', '菩': '費', '翡': '費',
    '謹': '護', '誇': '護', '獲': '護',
    '璽': '重', '亜': '並', '凋': '開', '焚': '奨',
    '杏': '査', '椴': '査', '瀕': '源', '某': '基',
    '藍': '監', '箪': '童', '粟': '票', '栗': '票',
    '閣': '間',
}
# Ambiguous misreads repaired only inside the exact wrong word context.
# Order matters: longer scoped rules must fire before shorter overlapping
# ones (施設幣備→施設整備 before 施設幣→施設費). Misread glyphs that also
# legitimately appear (誰/劇/閲/盤/最/圃/青/連/進/士/医/両/卜) stay scoped to
# the render-verified wrong contexts only.
REPAIR_WORDS = [
    # 幣 misencodes 整 in compounds and 費 in 施設費; longest first.
    ('施設幣備', '施設整備'), ('幣備', '整備'), ('調幣', '調整'),
    # A line wrap can split 幣備 across tokens (学校施設幣/備費), which the
    # shorter token-level rules corrupt into 施設費備; repair the join.
    ('施設幣', '施設費'), ('施設費備', '施設整備'),
    # 連→運 only inside these words (連絡/連携/連合/関連 are legitimate).
    ('連営', '運営'), ('連動', '運動'), ('連搬', '運搬'), ('連用', '運用'),
    # 輿→興 in 振興 words, →与 in 参与/与党 words.
    ('振輿', '振興'), ('参輿', '参与'), ('輿党', '与党'),
    # 拉→並/位, 坑→域/校, 士→土, 医→区 — all context-scoped.
    ('杉拉', '杉並'), ('単拉', '単位'),
    ('地坑', '地域'), ('学坑', '学校'),
    ('士木', '土木'), ('士のう', '土のう'), ('郷士', '郷土'),
    ('医交際', '区交際'), ('地医', '地区'), ('医民', '区民'), ('医市', '区市'),
    # Other scoped repairs verified against the render.
    ('蓮営', '運営'), ('蓮動', '運動'),
    ('購座', '講座'), ('套育', '食育'), ('套糧', '食糧'),
    ('健艇', '健康'),
    # v4-inspection additions (render-verified in observe/misread-groundtruth.md)
    ('務昔', '務費'), ('済昔', '済費'), ('勤昔', '勤費'), ('予備昔', '予備費'),
    ('需用貨', '需用費'), ('役務貨', '役務費'), ('共済貨', '共済費'),
    ('事務袋', '事務費'), ('渭掃', '清掃'), ('照備', '整備'), ('救備', '整備'),
    ('骰備', '整備'), ('調森', '調査'), ('健巌', '健康'), ('健痕', '健康'),
    ('介調', '介護'), ('速動', '運動'), ('運戸呂', '運営'), ('牒業', '農業'),
    ('嗅励', '奨励'), ('糖励', '奨励'), ('派憤', '派遣'), ('派潰', '派遣'),
    ('睛入', '購入'), ('振桔', '振替'), ('代蓉地', '代替地'), ('竜話', '電話'),
    ('推煎会', '推薦会'), ('推薗会', '推薦会'), ('文響', '文書'),
    ('測呈', '測量'), ('測贔', '測量'), ('基金租立金', '基金積立金'),
    ('指沸', '指導'), ('逍路', '道路'), ('距師', '医師'), ('董層', '重層'),
    ('甚金', '基金'), ('経らし', '暮らし'), ('・タ保育', '・夕保育'),
    ('振囲', '振興'), ('期H前', '期日前'), ('音〖一般', '部一般'),
    ('7肖', '消'), ('ガ円', '万円'), ('謂習', '講習'), ('稲調査', '盤調査'),
    ('速営', '運営'), ('速用', '運用'), ('速絡', '連絡'),
    ('上木', '土木'), ('上事', '工事'), ('青報', '情報'), ('劇齢', '高齢'),
    ('第竺者', '第三者'), ('竺療', '診療'), ('最観', '景観'), ('減最', '減量'),
    ('訪閲', '訪問'), ('時閣', '時間'), ('当悴', '充当'), ('計両', '計画'),
    ('管理誤', '管理課'), ('環境誤', '環境課'), ('整備誤', '整備課'),
    ('盤備', '整備'), ('骸備', '整備'), ('進族', '遺族'), ('生拝', '生涯'),
    ('稗行', '善行'), ('ロム', '合'), ('仮稀', '仮称'), ('公圃', '公園'),
    ('介證', '介護'), ('学カ', '学力'), ('スポーッ', 'スポーツ'),
    ('こ‘み', 'ごみ'),
    # settlement-2 (特別会計分冊) additions — render-verified in 0020 build.
    ('報醐', '報酬'), ('需用喘', '需用費'), ('介誨', '介護'),
    ('商額', '高額'), ('商齢者', '高齢者'), ('託齢者', '高齢者'),
    ('地城', '地域'), ('疇能', '器機能'), ('竿給', '等給'),
    ('貸等', '費等'), ('サービス貨', 'サービス費'),
    # 0021 国民健康保険: 療養昔の支給 → 療養費 (render-verified p14).
    ('療養昔', '療養費'),
    # 0021v2 国民健康保険: 国民健廉保険 → 国民健康保険 (render-verified p14,
    # 既存 健巌/健痕→健康 と同族)。s1・care圏に健廉の出現なし。
    ('健廉', '健康'),
    # 0021v2 行折返し分離 分 の ノ刀 系誤読 (render-verified p16)。文字層では
    # ‘ と ノ刀 が別wordのため pair 規則のみ (bare ノ刀 規則は見送り:
    # 全ドキュメントにbare出現なし、p3歳入圏の対も ‘付き)。
    ('‘ノ刀', '分'),
    # 0021v2 役務喘 → 役務費 (render-verified p17、既存 需用喘→需用費 と同族)。
    # s1・care圏に喘の出現なし(需用喘は既存規則で処理)。
    ('役務喘', '役務費'),
    # 卜 is genuinely printed in 卜訪問看護 (render-verified): keep it.
]
REPAIR_HITS = {}


def repair_text(value, context=None):
    """Repair text-layer misencodings; returns the printed reading."""
    result = value
    for wrong, right in REPAIR_WORDS:
        if wrong in result:
            REPAIR_HITS[wrong + '→' + right] = REPAIR_HITS.get(wrong + '→' + right, 0) + result.count(wrong)
            result = result.replace(wrong, right)
    for wrong, right in REPAIR_CHARS.items():
        if wrong in result:
            REPAIR_HITS[wrong + '→' + right] = REPAIR_HITS.get(wrong + '→' + right, 0) + result.count(wrong)
            result = result.replace(wrong, right)
    # 誰→護 except the legitimate 誰でも
    if '誰' in result:
        fixed = re.sub(r'誰(?!でも)', '護', result)
        if fixed != result:
            REPAIR_HITS['誰→護'] = REPAIR_HITS.get('誰→護', 0) + 1
            result = fixed
    if len(result) > 1 and '•' in result:
        result = result.replace('•', '・')
    # · (U+00B7) is the text-layer rendering of the printed fullwidth ・
    if '·' in result:
        REPAIR_HITS['·→・'] = REPAIR_HITS.get('·→・', 0) + result.count('·')
        result = result.replace('·', '・')
    return result


DEPT_SUFFIX = re.compile(
    r'(?:課|局|所|室|部|係|科|館|園|校|庁|事務所|センター|課・[課局所室部係科館校庁]|'
    r'局・[課局所室部係科館校庁]|所・[課局所室部係科館校庁]|'
    r'課・課・[課局所室部係科館校庁]|課・局・[課局所室部係科館校庁])+')


def repair_brackets(value, dept_parens=True):
    """Affiliation brackets 【課名】 misencode as ［］, （）, 課l, 課）, or drop
    the closer; normalize them when the contents end in a department suffix.
    dept_parens=False leaves parenthesized facility qualifiers ((本所),
    （私立幼稚園）, …) alone — only 事業-level names carry 【所管】."""
    value = value.replace('［', '【').replace('］', '】')
    # A second 【 before any 】 is a doubled opener (【地坑［子育て支援課］).
    value = re.sub(r'【([^【】]*)【', r'【\1', value)
    # 課 misread inside brackets (誤】, 課1, 課l).
    value = value.replace('誤】', '課】')
    value = re.sub(r'【([^【】（）］]{1,40}?' + DEPT_SUFFIX.pattern + r')[l1］）\)、】]',
                   r'【\1】', value)
    value = re.sub(r'【([^【】（）］]{1,40}?' + DEPT_SUFFIX.pattern + r')$',
                   r'【\1】', value)
    if dept_parens:
        value = re.sub(r'（([^（）【】］]{1,40}?' + DEPT_SUFFIX.pattern + r')[l1］）\)、】]',
                       r'【\1】', value)
        value = re.sub(r'（([^（）【】］]{1,40}?' + DEPT_SUFFIX.pattern + r')$',
                       r'【\1】', value)
    # Printed dept-list separators are '、' (misencoded ， or ．) and are
    # sometimes dropped entirely between two department names.
    value = re.sub(r'(?<=課)，|(?<=局)，|(?<=所)，', '、', value)
    value = re.sub(r'(?<=課)．|(?<=局)．|(?<=所)．', '、', value)
    # The text layer drops the '、' separator between two department names in
    # exactly the observed cases; keep this scoped so single names like
    # 課税課 (課…課) are never split.
    value = value.replace('管理課市街地整備課', '管理課、市街地整備課')
    value = value.replace('管理課杉並福祉事務所', '管理課、杉並福祉事務所')
    value = value.replace('課l', '課】')
    value = value.replace('課1', '課】')
    return value


FULLWIDTH = str.maketrans('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz',
                          '０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
                          'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ')


def repair_width(value):
    """Parenthesized groups print with fullwidth brackets and digits/letters;
    the text layer emits halfwidth variants. Normalize them."""
    def widen(match):
        inner = match[1]
        if match[0][0] == '(' or match[0][-1] == ')':
            REPAIR_HITS['()→（）'] = REPAIR_HITS.get('()→（）', 0) + 1
        widened = inner.translate(FULLWIDTH)
        if widened != inner:
            REPAIR_HITS['半角→全角'] = REPAIR_HITS.get('半角→全角', 0) + 1
        return '（' + widened + '）'

    return re.sub(r'[（(]([^（）()]{0,30}?)[）)]', widen, value)


def repair_name(value, dept_parens=True):
    """Full name-string repair: token-level rules, bracket normalization,
    then fullwidth restoration inside parenthesized groups."""
    return repair_width(repair_brackets(repair_text(value), dept_parens)) if value else value


# A printed '0' amount merges with the 備考 ○ marker the same way ('oo' at
# x≈974-990); its center falls right of the 不用額 band edge, so it needs the
# same split. Fire only for marker-family tokens (comma amounts untouched).
BOUNDARY_MARKER = re.compile(r'[0-9oO○〇●]*[oO○〇●][0-9oO○〇●]*')


def split_boundary_token(word):
    """Poppler merges a rightmost amount digit with the ○ marker of the 備考
    column (e.g. printed '1' + '○' extracted as '10' at x≈975-990). Split any
    all-digit token straddling x=982 into per-character words. A printed '0'
    amount merges the same way ('oo'); split marker-family tokens too so the
    amount-side fragment normalizes via DIGIT_FIX and the note-side fragment
    stays a heading marker."""
    if not (word['xMin'] < 982 < word['xMax']):
        return [word]
    if not (NUMBER.fullmatch(word['text']) or BOUNDARY_MARKER.fullmatch(word['text'])):
        return [word]
    span = word['xMax'] - word['xMin']
    per = span / len(word['text'])
    parts = []
    for i, ch in enumerate(word['text']):
        parts.append({**word, 'text': ch, 'frag': True,
                      'xMin': word['xMin'] + i * per,
                      'xMax': word['xMin'] + (i + 1) * per})
    return parts


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(path).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - PAGE_WIDTH) > .1 or abs(float(page.get('height')) - PAGE_HEIGHT) > .1:
            raise ValueError(f'Unmeasured page dimensions at {number}')
        words = []
        for w in page.findall('.//{*}word'):
            word = dict(text=repair_text(w.text or ''), **{k: float(v) for k, v in w.attrib.items()})
            words.extend(split_boundary_token(word))
        pages.append((number, words))
    if len(pages) != last - first + 1:
        raise ValueError('Incomplete Poppler page range')
    return pages




def lines(words):
    result = []
    for word in sorted(words, key=lambda w: (w['yMin'], w['xMin'])):
        if not result or word['yMin'] - result[-1][0]['yMin'] > 1.5:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w['xMin']) for row in result]


def text(words):
    result = []
    for row in lines(words):
        value = ''
        previous = None
        for word in row:
            if previous and word['xMin'] - previous['xMax'] > 1:
                value += ' '
            value += word['text']
            previous = word
        result.append(value)
    return '\n'.join(result) or None


def row_words(words, y):
    """Words of one printed row; shifted glyphs (△/0) sit ~1.6pt off the line."""
    return [w for w in words if y - 2.2 <= w['yMin'] < y + 3.2]


def band_amounts(row, bands, anomalies=None):
    """Assign each amount token to its band by the token's center x, then
    join the band's tokens left to right. Tokens split one glyph per word.
    A △ sign (text layer '•') sits a few points left of its digits and can
    drift into the previous band: it takes the band of the next token."""
    ordered = sorted(row, key=lambda w: w['xMin'])
    values = [[] for _ in bands]
    for index, w in enumerate(ordered):
        center = (w['xMin'] + w['xMax']) / 2
        if w['text'] == '•' and index + 1 < len(ordered):
            nxt = ordered[index + 1]
            if nxt['xMin'] - w['xMax'] < 15:
                center = (nxt['xMin'] + nxt['xMax']) / 2
        band = next((i for i, (left, right) in enumerate(bands) if left <= center < right), None)
        if band is None:
            continue
        values[band].append(w)
    result = []
    for tokens in values:
        if not tokens:
            result.append(None)
            continue
        value = ''.join(normalize(DIGIT_FIX.get(w['text'], w['text'])) for w in tokens)
        if not AMOUNT.fullmatch(value):
            # A printed literal instead of an amount (e.g. 繰越明許費 in the
            # 翌年度繰越額 column): keep it verbatim and flag it.
            if anomalies is not None:
                anomalies.append({'issue': 'literal value in amount column',
                                  'value': value})
            result.append(value)
            continue
        result.append(value)
    return result


def location(page, y, words):
    return {'物理頁': page, '上端': y, '下端': max(w['yMax'] for w in words)}


def executed(words, y, anomalies):
    right = [w for w in row_words(words, y)
             if EXEC_BANDS[0][0] - 6 <= w['xMin'] and w['xMin'] < 980]
    result = {key: value for key, value in zip(EXECUTED, band_amounts(right, EXEC_BANDS, anomalies))}
    result['翌年度繰越額_区分'] = None
    # 繰越明許費 rows print the label on the row and the carried amount on a
    # sub-line ~12pt below it, inside the same column band. The printed literal
    # is preserved as the carryover kind, not folded into the amount.
    carryover = result['翌年度繰越額']
    if carryover is not None and not AMOUNT.fullmatch(carryover):
        result['翌年度繰越額_区分'] = carryover
        result['翌年度繰越額'] = None
        sub = [w for w in words if EXEC_BANDS[1][0] <= w['xMin'] < EXEC_BANDS[1][1] + 4
               and y + 6 <= w['yMin'] < y + 22]
        # The sub-line must not itself carry another carryover label.
        if not any('繰越' in w['text'] for w in words
                   if y + 6 <= w['yMin'] < y + 22):
            value = amount_text(sub)
            if value is not None:
                anomalies.append({'issue': 'carryover subline merged', 'y': y,
                                  'value': value, 'label': carryover})
                result['翌年度繰越額'] = value
    return result


def subject_record(words, row, page, y, name_high, anomalies, next_row=None):
    labels = [w for w in row if w['xMin'] < SUBJ_BANDS[0][0]]
    joined = ''.join(w['text'] for w in labels)
    if joined.startswith('歳出') and '計' in joined:
        near = row_words(words, y)
        return 'total', {**{key: value for key, value in zip(BUDGET, band_amounts(near, SUBJ_BANDS, anomalies))},
                         **executed(words, y, anomalies)}
    # The marker is the leftmost label word that reads as a number. A parent's
    # wrapped name tail can sit further left on the same baseline (and a
    # printed '1' can reach the text layer as 'l'/'I').
    digits = [w for w in labels
              if NUMBER.match(DIGIT_FIX.get(w['text'], w['text']))]
    if not digits:
        raise ValueError(f'Unnumbered printed path at page {page}, y={y}')
    marker = min(digits, key=lambda w: w['xMin'])
    match = re.match(r'([0-9]+)(.*)', DIGIT_FIX.get(marker['text'], marker['text']))
    level = '款' if marker['xMin'] < 60 else '項' if marker['xMin'] < 140 else '目'
    name_words = [w for w in words if marker['xMin'] + .2 <= w['xMin'] and w['xMax'] <= 217
                  and y - 7.5 <= w['yMin'] < name_high and w is not marker]
    # A name tail sharing the next row's baseline stays left of that row's
    # own marker; recover it into this record's name.
    if next_row is not None:
        next_labels = [w for w in next_row if w['xMin'] < SUBJ_BANDS[0][0]]
        next_marker = next((w for w in sorted(next_labels, key=lambda w: w['xMin'])
                            if NUMBER.match(DIGIT_FIX.get(w['text'], w['text']))), None)
        if next_marker is not None:
            name_words += [w for w in next_labels
                           if marker['xMin'] + .2 <= w['xMin']
                           and w['xMax'] < next_marker['xMin']]
    if match[2]:
        name_words.append({**marker, 'text': match[2],
                           'xMin': marker['xMin'] + 4.5 * len(match[1])})
    near = row_words(words, y)
    return 'subject', {'level': level, '番号': match[1], '名称': repair_name(''.join(w['text'] for w in sorted(name_words, key=lambda w: (w['yMin'], w['xMin'])))),
                       **{key: value for key, value in zip(BUDGET, band_amounts(near, SUBJ_BANDS, anomalies))},
                       **executed(words, y, anomalies),
                       '備考': None, **location(page, y, labels + name_words)}


def setsu_record(words, row, page, y, name_high, anomalies):
    markers = [w for w in row if SETSU_NUM[0] <= w['xMin'] and w['xMax'] <= SETSU_NUM[1]]
    if len(markers) != 1 or not NUMBER.fullmatch(markers[0]['text']):
        raise ValueError(f'Missing section number at page {page}, y={y}')
    name_words = [w for w in words if SETSU_NAME[0] <= w['xMin'] and w['xMax'] <= SETSU_BANDS[0][0]
                  and y - 7.5 <= w['yMin'] < name_high]
    near = row_words(words, y)
    return {'区分_番号': markers[0]['text'], '区分_名称': repair_name(''.join(w['text'] for w in sorted(name_words, key=lambda w: (w['yMin'], w['xMin'])))),
            '金額': band_amounts(near, SETSU_BANDS, anomalies)[0],
            **executed(words, y, anomalies),
            '備考': None, **location(page, y, markers + name_words)}



AMOUNT_CHARS = frozenset('0123456789,•゜OlI|△')


def amount_text(words):
    value = ''.join(normalize(DIGIT_FIX.get(w['text'], w['text']))
                    for w in sorted(words, key=lambda w: w['xMin']))
    return value if AMOUNT.fullmatch(value) else None


def split_row(row):
    """The printed amount is the contiguous run of digit-like tokens at the
    row's right edge; names may carry digits mid-row (号・条 numbers)."""
    amounts = []
    next_x = None
    for w in reversed(row):
        # Stray digits can sit far left of an amount (e.g. a misprinted '1'
        # 40pt ahead of '22,612,264'); amount digits pack within ~5pt.
        if (w['text'] and all(ch in AMOUNT_CHARS for ch in w['text'])
                and (next_x is None or next_x - w['xMax'] <= 8)):
            amounts.insert(0, w)
            next_x = w['xMin']
        else:
            break
    if not any(ch in '0123456789゜' for w in amounts for ch in w['text']):
        amounts = []
    return row[:len(row) - len(amounts)], amounts


def is_breakdown(cell):
    """A ruled cell is a breakdown when it holds numbered/heading items or
    repeated name+amount rows; remark cells carry free text only. Lines that
    read as dates/resolution references never count as items."""
    headings = numbered = pairs = 0
    for index, (page, row) in enumerate(cell['rows']):
        names, amounts = split_row(row)
        if not names:
            continue
        first = names[0]
        if (first['text'] == '0' or first['text'].startswith(('〇', '○', 'O'))) and first['xMin'] < 990:
            headings += 1
        elif (NUMBER.fullmatch(first['text'].replace('l', '1')) and first['xMin'] < 1006
              and len(names) > 1):
            numbered += 1
        elif amounts and not ANNOTATION.search(''.join(w['text'] for w in names)):
            pairs += 1
    return headings > 0 or numbered > 0 or pairs >= 2


ANNOTATION = re.compile(r'流用|充当|繰越分不用額|前年度繰越|議決|不用額|説明|流$|から流')
DATED = re.compile(r'[0-9]+年|[0-9]+号')


def parse_breakdown(cell, anomalies):
    """Parse one breakdown stream into the item tree; returns (items, remarks).
    cell['rows'] are (page, words) pairs so items keep their own print page."""
    stack = []
    items = []
    remarks = []
    open_item = None    # deepest item still waiting for its amount
    saw_item = False
    carry = None        # leading digit of an amount split across lines
    annotation_zone = False

    def close_deeper(level):
        while stack and stack[-1]['level'] >= level:
            stack.pop()

    rows = cell['rows']
    for index, (page, row) in enumerate(rows):
        names, amounts = split_row(row)
        if names and len(amounts) == 1 and len(amounts[0]['text']) == 1 and amounts[0]['xMin'] >= 1100:
            carry = amounts[0]
            amounts = []
        elif carry is not None:
            anomalies.append({'page': cell['page'], 'y': row[0]['yMin'],
                              'issue': 'dangling leading digit', 'text': carry['text']})
            carry = None
        if not names:
            if amounts:
                value = amount_text(amounts)
                if value is None:
                    raise ValueError(f'Unmeasured remarks amount at page {page}, y={row[0]["yMin"]}')
                if carry is not None:
                    value = carry['text'] + value
                    anomalies.append({'page': page, 'y': row[0]['yMin'],
                                      'issue': 'wrapped amount digit', 'value': value})
                    carry = None
                if open_item is None or open_item['金額'] is not None:
                    anomalies.append({'page': page, 'y': row[0]['yMin'],
                                      'issue': 'orphan amount', 'value': value})
                    remarks.append(value)
                else:
                    open_item['金額'] = value
                    open_item['下端'] = row[0]['yMax']
            continue
        # Multi-digit item numbers arrive as separate tokens ('1'+'7' for 17);
        # merge all leading digit tokens inside the number column.
        names = list(names)
        while (len(names) > 1 and names[0]['xMin'] >= 985
               and NUMBER.fullmatch(names[0]['text'])
               and NUMBER.fullmatch(names[1]['text']) and names[1]['xMin'] < 1006):
            names[0] = {**names[0], 'text': names[0]['text'] + names[1]['text'],
                        'xMax': names[1]['xMax']}
            del names[1]
        leading = names[0]
        name_full = ''.join(w['text'] for w in names)
        value = amount_text(amounts) if amounts else None
        is_heading = False
        head_name = name_full
        if leading['xMin'] < 990:
            first_text = leading['text']
            if first_text in ('0', '〇', '○', 'O', 'o', '●'):
                is_heading = True
                head_name = ''.join(w['text'] for w in names[1:])
            elif first_text[0] in '〇○O●' and len(first_text) > 1:
                is_heading = True
                head_name = first_text[1:] + ''.join(w['text'] for w in names[1:])
                anomalies.append({'page': page, 'y': row[0]['yMin'],
                                  'issue': 'merged heading glyph'})
            elif first_text.startswith('0') and len(first_text) > 1 and not first_text[1].isdigit():
                is_heading = True
                head_name = first_text[1:] + ''.join(w['text'] for w in names[1:])
                anomalies.append({'page': page, 'y': row[0]['yMin'],
                                  'issue': 'merged heading glyph'})
        # A printed ○ marker can reach the text layer twice: a stray '0'
        # token plus a '〇…' word (e.g. 0 + 〇介護認定調査【介護保険課】).
        # Names never legitimately start with a marker glyph, so strip one.
        if is_heading and head_name[:1] in '0〇○Oo●':
            head_name = head_name[1:]
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'duplicated heading marker'})
        number_token = leading['text'].replace('l', '1').replace('I', '1')
        is_numbered = (not is_heading and NUMBER.fullmatch(number_token)
                       and leading['xMin'] < 1006 and len(names) > 1)
        # A lone marker digit (e.g. a stray '0' in the heading column) is not
        # an item: keep it as remark text rather than a name-less leaf.
        if is_heading and not head_name.strip() and value is None:
            remarks.append(''.join(w['text'] for w in row))
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'marker-only line'})
            continue
        if is_numbered and not ''.join(w['text'] for w in names[1:]).strip():
            remarks.append(''.join(w['text'] for w in row))
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'marker-only line'})
            continue
        if is_heading or is_numbered:
            annotation_zone = False
            level = 0 if is_heading else (1 if leading['xMin'] < 995.5 else 2)
            close_deeper(level)
            if leading['text'] != number_token:
                anomalies.append({'page': page, 'y': row[0]['yMin'],
                                  'issue': 'number glyph variant', 'text': leading['text']})
            parent = stack[-1] if level and stack else None
            if level and parent is None:
                anomalies.append({'page': page, 'y': row[0]['yMin'],
                                  'issue': 'item without printed parent'})
            item = {'level': level, '番号': None if is_heading else number_token,
                    '名称': head_name if is_heading else ''.join(w['text'] for w in names[1:]),
                    '名称_x': names[1]['xMin'] if len(names) > 1 else leading['xMin'],
                    '金額': value, 'parent': parent,
                    '物理頁': page, '上端': row[0]['yMin'], '下端': row[0]['yMax']}
            stack.append(item)
            items.append(item)
            open_item = item
            saw_item = True
            continue
        # An affiliation line 【課名】 (optionally carrying the biz total)
        # completes the open 事業 name and amount; it is not an item. The biz
        # name tail can precede the bracket on the same line
        # (国民審査【選挙管理委員会事務局】 completing 衆議院議員選挙及び…).
        probe = repair_brackets(name_full)
        if '【' in probe and (probe.startswith('【')
                             or (open_item is not None and open_item['level'] == 0
                                 and open_item['金額'] is None)):
            biz = next((it for it in reversed(stack) if it['level'] == 0), None)
            if biz is not None:
                biz['名称'] += name_full
                biz['下端'] = row[0]['yMax']
                if value is not None:
                    if biz['金額'] is None:
                        biz['金額'] = value
                    elif biz['金額'] != value:
                        anomalies.append({'page': page, 'y': row[0]['yMin'],
                                          'issue': 'conflicting biz total',
                                          'value': value, 'held': biz['金額']})
                anomalies.append({'page': page, 'y': row[0]['yMin'],
                                  'issue': 'affiliation total line'})
                continue
        # Explanation notes (流用・充当・繰越分不用額・議決・説明) are not
        # expenditure items; they stay remarks and open an annotation zone
        # until the next heading/numbered line.
        if ANNOTATION.search(name_full):
            annotation_zone = True
            remarks.append(''.join(w['text'] for w in row))
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'annotation inside breakdown'})
            continue
        if annotation_zone and not is_numbered:
            remarks.append(''.join(w['text'] for w in row))
            continue
        # Wrapped name of an item still awaiting its amount: continuations
        # align with the item's name column, except name tails that wrap all
        # the way back to the left margin — those keep their own amount too.
        if (open_item is not None and open_item['金額'] is None
                and (abs(leading['xMin'] - open_item['名称_x']) <= 9
                     or value is not None)):
            open_item['名称'] += name_full
            open_item['下端'] = row[0]['yMax']
            if value is not None:
                open_item['金額'] = value
            continue
        # A new unnumbered item: name+amount on one line, or a name line
        # followed by an amount-only line.
        nxt = rows[index + 1] if index + 1 < len(rows) else None
        n_names, n_amounts = split_row(nxt[1]) if nxt is not None else ([], [])
        # An unmarked name in the heading column followed by a 【課名】 line is
        # a 事業 heading whose ○ marker never reached the text layer.
        if (value is None and leading['xMin'] < 998 and nxt is not None
                and n_names and repair_brackets(
                    ''.join(w['text'] for w in n_names)).startswith('【')):
            close_deeper(0)
            item = {'level': 0, '番号': None, '名称': name_full,
                    '名称_x': leading['xMin'], '金額': None, 'parent': None,
                    '物理頁': page, '上端': row[0]['yMin'], '下端': row[0]['yMax']}
            stack.insert(0, item)
            items.append(item)
            open_item = item
            saw_item = True
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'unmarked heading'})
            continue
        is_pair_item = value is not None or (nxt is not None and not n_names and n_amounts
                                             and len(name_full) > 2)
        if is_pair_item:
            # An unmarked name starting in the heading column is a 事業 whose
            # ○ marker was lost to the text layer (e.g. merged into digits).
            level = 0 if leading['xMin'] < 998 else (min(stack[-1]['level'] + 1, 2) if stack else 1)
            if level != 0 and stack and len(stack) <= 2 and leading['xMin'] < stack[-1]['名称_x'] - 4:
                level = 1
            close_deeper(level)
            parent = stack[-1] if level and stack else None
            item = {'level': level, '番号': None, '名称': name_full,
                    '名称_x': leading['xMin'], '金額': value,
                    'parent': parent,
                    '物理頁': page, '上端': row[0]['yMin'], '下端': row[0]['yMax']}
            stack.append(item)
            items.append(item)
            open_item = item
            saw_item = True
            anomalies.append({'page': page, 'y': row[0]['yMin'],
                              'issue': 'unnumbered item'})
            continue
        # A wrapped name tail after the amount was already assigned: very short
        # fragments aligned to the item's name column continue the name.
        if (open_item is not None and value is None and len(name_full) <= 6
                and abs(leading['xMin'] - open_item['名称_x']) <= 9):
            open_item['名称'] += name_full
            open_item['下端'] = row[0]['yMax']
            continue
        remarks.append(''.join(w['text'] for w in row))
        anomalies.append({'page': page, 'y': row[0]['yMin'],
                          'issue': 'text inside breakdown'})
    if open_item is not None and open_item['金額'] is None and open_item['level'] != 0:
        anomalies.append({'page': cell['page'], 'issue': 'item without amount',
                          'name': open_item['名称']})
    return items, remarks


def build(pages):
    """Assemble leaf rows; remarks-column lines attach to the subject whose
    printed row region contains them (breakdowns go to that subject's stream)."""
    current = {}
    parents = []
    total_rows = []
    anomalies = []
    cells_seen = []
    anchors = []          # (page, y, kind, path, record, context), document order
    setsu_rows = []
    breakdown_rows = []
    subject_anchors = []  # subject anchors only, document order
    streams = {}          # subject record id -> {record, context, rows, page}
    stream_order = []

    for page, words in pages:
        body = [w for w in words if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        events = []
        for row in lines(body):
            labelled = [w for w in row if w['xMin'] < SUBJ_BANDS[0][0]]
            if labelled and any(SUBJ_BANDS[0][0] <= w['xMin'] < SUBJ_BANDS[-1][1]
                                and (AMOUNT.fullmatch(normalize(w['text'])) or w['text'] in GLYPH_FIX)
                                for w in row):
                events.append((row[0]['yMin'], 'subject', row))
            if any(SETSU_NUM[0] <= w['xMin'] and w['xMax'] <= SETSU_NUM[1] and NUMBER.fullmatch(w['text'])
                   for w in row):
                events.append((row[0]['yMin'], 'setsu', row))
        events.sort(key=lambda e: e[0])
        if len(events) != len({round(e[0], 1) for e in events}):
            raise ValueError(f'Shared subject/section baseline at page {page}')
        page_anchors = []
        # Wrapped names run to the next printed line of the SAME kind: a 目
        # name may span lines carrying unrelated 節 rows, and a 節 name may
        # span lines carrying subject rows on the left printed page.
        subject_ys = [e[0] for e in events if e[1] == 'subject']
        setsu_ys = [e[0] for e in events if e[1] == 'setsu']
        subject_rows = [e[2] for e in events if e[1] == 'subject']
        subject_index = 0
        for index, (y, kind, row) in enumerate(events):
            bound_list = subject_ys if kind == 'subject' else setsu_ys
            name_high = next((by for by in bound_list if by > y), BODY_BOTTOM) - 1.0
            if kind == 'subject':
                next_row = (subject_rows[subject_index + 1]
                            if subject_index + 1 < len(subject_rows) else None)
                subject_index += 1
                which, record = subject_record(body, row, page, y, name_high, anomalies,
                                               next_row=next_row)
                if which == 'total':
                    total_rows.append({'page': page, 'y': y, **record})
                    continue
                level = record['level']
                if level == '款':
                    current = {}
                elif level == '項':
                    current.pop('目', None)
                current[level] = record
                path = tuple(current[a]['番号'] for a in ('款', '項', '目') if a in current)
                parents.append({**record, 'path': path, 'record_ref': record})
                page_anchors.append((page, y, 'subject', path, record, dict(current)))
                subject_anchors.append(page_anchors[-1])
            else:
                if set(current) != {'款', '項', '目'}:
                    raise ValueError(f'Missing printed path at page {page}, y={y}')
                record = setsu_record(body, row, page, y, name_high, anomalies)
                path = tuple(current[a]['番号'] for a in ('款', '項', '目')) + (record['区分_番号'],)
                page_anchors.append((page, y, 'setsu', path, record, dict(current)))
        anchors.extend(page_anchors)
        for a in page_anchors:
            if a[2] != 'setsu':
                continue
            path, _, record, context = a[3], a[2], a[4], a[5]
            # Materialize the leaf after remark streams run, so 目_備考
            # additions from breakdown parsing are visible on the lineage.
            setsu_rows.append((page, record['上端'], record, context))
        # Remarks-column lines route to the latest subject anchor's stream.
        # Ownership follows document order: the last subject anchor before
        # this line, comparing (page, y) so later anchors never claim earlier
        # lines and page-top continuations keep the previous subject.
        # Amount cells sit right of the note column's rule (x=975); a token
        # straddling x=982 is split so a merged ○ marker is recovered, but the
        # amount-side fragments (x<982) must not leak into the remark stream —
        # e.g. the last digit of 1,101,960 in 不用額 fakes a '0' marker/item.
        note_rows = lines([w for w in body if w['xMin'] >= NOTE_LEFT
                           and not (w.get('frag') and w['xMin'] < 982)])
        for row in note_rows:
            y = row[0]['yMin']
            earlier = [a for a in subject_anchors if (a[0], a[1]) <= (page, y + 1.5)]
            owner = earlier[-1] if earlier else None
            if owner is None:
                raise ValueError(f'Remarks line without an owner at page {page}, y={y}')
            key = id(owner[4])
            if key not in streams:
                streams[key] = {'record': owner[4], 'context': owner[5], 'rows': [], 'page': page}
                stream_order.append(key)
            streams[key]['rows'].append((page, row))
        cells_seen.append({'page': page, 'subject_rows': len(page_anchors),
                           'note_lines': len(note_rows)})

    for key in stream_order:
        stream = streams[key]
        record, context = stream['record'], stream['context']
        pseudo = {'rows': stream['rows'], 'page': stream['page']}
        if is_breakdown(pseudo):
            items, remarks = parse_breakdown(pseudo, anomalies)
            cells_seen.append({'kind': 'breakdown', 'page': stream['page'],
                               'owner': record['番号'], 'items': len(items)})
            if remarks:
                addition = '\n'.join(remarks)
                record['備考'] = addition if record['備考'] is None else record['備考'] + '\n' + addition
            leaves = [it for it in items if not any(o['parent'] is it for o in items)]
            for it in leaves:
                leaf = {}
                for level in ('款', '項', '目'):
                    if level in context:
                        leaf.update({level + '_' + k: v for k, v in context[level].items() if k != 'level'})
                chain = []
                node = it
                while node is not None:
                    chain.append(node)
                    node = node['parent']
                for node in chain:
                    prefix = {0: '実施事業_', 1: '項目_', 2: '細目_'}[node['level']]
                    if node['level']:
                        leaf[prefix + '番号'] = node['番号']
                    leaf[prefix + '名称'] = repair_name(node['名称'], node['level'] == 0)
                    leaf[prefix + '金額'] = node['金額']
                leaf['物理頁'] = it['物理頁']
                leaf['上端'] = it['上端']
                leaf['下端'] = it['下端']
                breakdown_rows.append((it['物理頁'], it['上端'], leaf))
        else:
            remarks = [repair_name(''.join(w['text'] for w in row[1])) for row in stream['rows']]
            cells_seen.append({'kind': 'remark', 'page': stream['page'], 'owner': record['番号']})
            if remarks:
                # A remark confined to one 節 band belongs to that 節.
                setsu = [a for a in anchors if a[2] == 'setsu'
                       and stream['rows'] and a[4] is not record
                       and a[5].get('目') is context.get('目')]
                def band_end(a):
                    return next((b[1] for b in anchors if b[0] == a[0] and b[1] > a[1]), BODY_BOTTOM + 30)
                band = [a for a in setsu
                        if all(r[0] == a[0] and a[1] - 1 <= r[1][0]['yMin'] < band_end(a)
                               for r in stream['rows'])]
                target = band[0][4] if len(band) == 1 else record
                addition = '\n'.join(remarks)
                target['備考'] = addition if target['備考'] is None else target['備考'] + '\n' + addition
                if len(band) == 1:
                    anomalies.append({'issue': 'setsu-scoped remark', 'page': stream['page'],
                                      'setsu': band[0][3]})

    # 目 with neither 節 rows nor breakdown items is its own leaf row.
    with_setsu = {id(a[5]['目']) for a in anchors if a[2] == 'setsu'}
    with_detail = {key for key in stream_order
                   if is_breakdown({'rows': streams[key]['rows'], 'page': 0})}
    for record in parents:
        if record['level'] != '目' or id(record['record_ref']) in with_setsu or id(record['record_ref']) in with_detail:
            continue
        ctx = next((a[5] for a in anchors if a[4] is record['record_ref']), None)
        setsu_rows.append((record['物理頁'], record['上端'], {}, ctx))
    if len(total_rows) > 1:
        raise ValueError('Expected one printed detail expenditure total')
    out = []
    for page, y, record, context in setsu_rows:
        leaf = {}
        for level in ('款', '項', '目'):
            leaf.update({level + '_' + k: v for k, v in context[level].items() if k != 'level'})
        leaf.update({'節_' + k.removeprefix('区分_'): v for k, v in record.items()
                     if k != 'level'})
        out.append((page, y, leaf))
    return out, breakdown_rows, parents, cells_seen, total_rows, anomalies


LINEAGE = [f'{level}_{k}' for level in ('款', '項', '目')
           for k in ('番号', '名称', *BUDGET, *EXECUTED, '翌年度繰越額_区分',
                     '備考', '物理頁', '上端', '下端')]
SETSU_COLUMNS = (LINEAGE + [f'節_{k}' for k in ('番号', '名称', '金額', *EXECUTED,
                                                '翌年度繰越額_区分', '備考',
                                                '物理頁', '上端', '下端')])
BREAKDOWN_COLUMNS = (LINEAGE + ['実施事業_名称', '実施事業_金額', '項目_番号',
                                '項目_名称', '項目_金額', '細目_番号', '細目_名称',
                                '細目_金額', '物理頁', '上端', '下端'])


def metadata(columns, account, kind):
    amounts = [c for c in columns if c in BUDGET + EXECUTED
               or c.endswith('_金額') or any(c.endswith('_' + k) for k in BUDGET + EXECUTED)]
    contexts = []
    for level in ('款', '項', '目'):
        contexts.append({'columns': [c for c in columns if c.startswith(level + '_')],
                         'header_path': ['科目', level],
                         'grain_columns': [level + '_番号', level + '_物理頁', level + '_上端']})
    if kind == 'details':
        contexts.append({'columns': [c for c in columns if c.startswith('節_')],
                         'header_path': ['節'], 'semantic_role': 'setsu',
                         'grain_columns': ['目_物理頁', '目_上端', '節_番号']})
    else:
        contexts.append({'columns': [c for c in columns if c.startswith(('実施事業_', '項目_', '細目_'))],
                         'header_path': ['備考'],
                         'grain_columns': ['物理頁', '上端']})
    note = ('原典の同一目には節の財政明細行と目単位の事業内訳という親子関係のない2つの印字分解が併記される。'
            '所属する款・項・目の予算5列・執行3列・備考・印字位置を反復する。'
            '内訳項目行は備考欄の罫線セルに印字される支出済額の階層内訳で、'
            '事業（印字○、文字層では0）→番号付き項目→番号付き細目の最末端を葉とし、'
            '事業名【所管】・項目・細目の名称と金額を階層列へ展開する。'
            '内訳金額欄に印字見出しはなく、右端整列の金額を各項目へ対応させる。'
            '番号のない名称+金額行は番号NULLの内訳項目。'
            '節も内訳もない目は目自体を葉として節表に載せる。'
            '内訳項目の所属は罫線セルが覆う節ブロックの目まで（個々の節への割当は原典にない）。'
            '備考欄の金額構造を持たない単文はowner行の備考へ保持する。'
            '金額セルは1文字ずつの語に分かれるため列内で結合し、'
            '文字層の「•」「゜」は印字の「△」「0」へ復元する。'
            '原典は1物理頁=左右印字2頁の見開きで、左頁に科目・予算、右頁に節・執行・備考が印字される。'
            f'見開き末尾の「{account}」会計標・各頁の実行見出し・印字頁番号は明細ではないため除く。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Suginami general settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '131156' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Suginami text settlement expenditure only')
    account = options.get('account', '一般会計')
    selected = [p for scope in source['scope'] if scope['account'] == account
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if not selected or sorted(selected) != list(range(selected[0], selected[-1] + 1)):
        raise ValueError(f'Measured scope for {account} must be one contiguous page range')
    destination = Path(destination)
    observations = destination / 'suginami-observations'
    observations.mkdir(parents=True, exist_ok=True)
    pages = observe(source['path'], selected[0], selected[-1], observations / 'detail-bbox.html')
    setsu_rows, breakdown_rows, parents, cells_seen, total_rows, anomalies = build(pages)
    (observations / 'parents.json').write_text(json.dumps({'detail': parents}, ensure_ascii=False, indent=2) + '\n')
    (observations / 'note-cells.json').write_text(json.dumps(
        {'cells': cells_seen}, ensure_ascii=False, indent=2) + '\n')
    (observations / 'totals.json').write_text(json.dumps(total_rows, ensure_ascii=False, indent=2) + '\n')
    (observations / 'anomalies.json').write_text(json.dumps(anomalies, ensure_ascii=False, indent=2) + '\n')
    (observations / 'repairs.json').write_text(json.dumps(
        {'hits': dict(sorted(REPAIR_HITS.items()))}, ensure_ascii=False, indent=2) + '\n')
    prefix = options['table_prefix']
    emit = options.get('emit') or ('details', 'notes')
    results = {}
    for kind, collected, order in (('details', setsu_rows, SETSU_COLUMNS),
                                   ('notes', breakdown_rows, BREAKDOWN_COLUMNS)):
        if kind not in emit:
            continue
        collected.sort(key=lambda r: (r[0], r[1]))
        rows = [{k: row.get(k) for k in order} for _, _, row in collected]
        if not rows:
            raise ValueError(f'No {kind} rows produced')
        columns = tuple(ParquetColumn(k, 'BIGINT' if k == '物理頁' or k.endswith('_物理頁')
                                      else 'DOUBLE' if k in ('上端', '下端') or k.endswith(('_上端', '_下端'))
                                      else 'VARCHAR') for k in order)
        table_id = f'{prefix}-{kind}'
        output = write_conversion(destination / (table_id + '.parquet'), rows, columns=columns,
                                  context=ConversionContext(source['sha256'], table_id, __file__))
        results[table_id] = {'path': Path(output.path), 'metadata': metadata(order, account, kind)}
    return results
