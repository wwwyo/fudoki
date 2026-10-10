"""Assemble Kiyose's late-elderly medical settlement spread from Poppler word boxes.

Measured scope only: jurisdiction 132217, fiscal 2025 settlement expenditure,
後期高齢者医療特別会計, physical pages 159-164 (three left/right spreads).
Left page carries 款・項・目 budget rows and 法定節 rows; the right page carries
支出済額・不用額 values (one pair per left detail row, same order, measured
per-spread y offset) and an independent 備考 flow (事業 → 節見出し → 細目 →
細々目, 所属, 流用注記). The two right-page flows share baselines by coincidence,
so they are parsed independently and never joined by height or name alone.
Raw grain is one row per explanation leaf; businesses are assigned to 目 by
position, and 法定節 correspondence is accepted only for (節番号 match,
目内・事業跨ぎ L1 amount sum == 節支出済額). Unprinted columns
(翌年度繰越額 3 sub-columns, 継続費繰越, 予備費流用増減) are not emitted.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

ORIGIN_SHA = "55219fb3c04d2cca0ecb4fea979111040beccafdedd596ec09a553317bbaeb3d"
FIRST_PAGE, LAST_PAGE = 159, 164
PAGE_WIDTH, PAGE_HEIGHT = 595.276, 841.89
ACCOUNT = "後期高齢者医療特別会計"

AMOUNT = re.compile(r"△?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
NUMBERED = re.compile(r"(\d+)\s+(.*)")
RYUYO = re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d{2}(から|へ)流用")
SYOZOKU = re.compile(r"【.+】")

LEFT_BODY_TOP, LEFT_BODY_BOTTOM = 135.0, 745.0
RIGHT_BODY_TOP, RIGHT_BODY_BOTTOM = 135.0, 745.0
AB_SPLIT_X = 289.0  # A words start below, B words start at/above (measured gap 287.6/290.7)
LEVEL_BANDS = [(290.0, 296.0), (297.0, 304.0), (305.0, 313.0), (313.0, 321.0)]
Y_TOL = 4.0


def _num(text):
    negative = text.startswith("△")
    return -int(text[1:].replace(",", "")) if negative else int(text.replace(",", ""))


def observe(pdf, first, last, path):
    subprocess.run(["pdftotext", "-f", str(first), "-l", str(last), "-bbox-layout",
                    str(pdf), str(path)], check=True)
    pages = {}
    for number, page in enumerate(ET.parse(path).findall(".//{*}page"), first):
        if abs(float(page.get("width")) - PAGE_WIDTH) > 0.1 or abs(float(page.get("height")) - PAGE_HEIGHT) > 0.1:
            raise ValueError(f"Unmeasured page dimensions at {number}")
        pages[number] = [dict(text=w.text or "", **{k: float(v) for k, v in w.attrib.items()})
                         for w in page.findall(".//{*}word")]
    if sorted(pages) != list(range(first, last + 1)):
        raise ValueError("Incomplete Poppler page range")
    return pages


def baselines(words):
    rows = []
    for word in sorted(words, key=lambda w: (w["yMin"], w["xMin"])):
        if (word["text"] or "").strip() == "":
            continue
        if not rows or word["yMin"] - rows[-1][0]["yMin"] > 1.5:
            rows.append([])
        rows[-1].append(word)
    return [sorted(row, key=lambda w: w["xMin"]) for row in rows]


def line_text(words):
    value, previous = "", None
    for word in words:
        if previous is not None and word["xMin"] - previous["xMax"] > 1.0:
            value += " "
        value += word["text"]
        previous = word
    return value


def split_amount_tail(words, page_number, y):
    """Split trailing amount words from name words on one 備考 baseline.

    Bare numbers (事業/節/細目番号) also match AMOUNT, so amounts are identified
    by position (measured amount zone x>=400), never by text alone.
    """
    amounts = [w for w in words if w["xMin"] >= 400 and AMOUNT.fullmatch(w["text"])]
    tail = [w for w in words if w["xMin"] < 400]
    if len(amounts) != 1 or not tail:
        raise ValueError(f"備考 baseline needs exactly one trailing amount at page {page_number},"
                         f" y={y}: {[w['text'] for w in words]}")
    # Name numbers (事業/節/細目番号) also match AMOUNT; they live below x=321.
    if any(AMOUNT.fullmatch(w["text"]) and w["xMin"] >= 321 for w in tail):
        raise ValueError(f"Stray amount inside 備考 name at page {page_number},"
                         f" y={y}: {[w['text'] for w in words]}")
    if any(w["xMax"] > amounts[0]["xMin"] for w in tail):
        raise ValueError(f"備考 amount is not trailing at page {page_number},"
                         f" y={y}: {[w['text'] for w in words]}")
    return tail, amounts[0]["text"]


def parse_left(page_number, words, current):
    """Return (detail_rows, total) for one left page, extending cross-page state.

    detail_rows are 款・項・目・節 dicts in printed order. Multi-line names are
    joined with newline. The 歳出合計統制行 is returned separately, never a row.
    `current` carries 款・項・目 context across spreads (款2 opens on p159,
    its 項・目・節 continue on p161); callers pass one dict for the whole scope.
    """
    text_all = "".join(w["text"] for w in words)
    for required in ("当初予算額", "補正予算額", "予備費支出", "繰越事業費", "区分", "金額"):
        if required not in text_all:
            raise ValueError(f"Unmeasured left header at page {page_number}: missing {required}")
    rows, total = [], None
    for line in baselines([w for w in words if LEFT_BODY_TOP <= w["yMin"] < LEFT_BODY_BOTTOM]):
        # Bare numbers also match AMOUNT: 款項目 numbers (x<110) and 節 numbers
        # (measured band 410-426) are never amounts; amounts live at x>=130 outside it.
        def is_amount(w):
            return w["xMin"] >= 130 and not 410 <= w["xMin"] < 426 and AMOUNT.fullmatch(w["text"])
        amounts = [w for w in line if is_amount(w)]
        head = [w for w in line if not is_amount(w)]
        if not head:
            raise ValueError(f"Amount-only baseline at page {page_number}, y={line[0]['yMin']}")
        first = head[0]
        if first["text"] == "歳":
            joined = "".join(w["text"] for w in head)
            if not joined.startswith("歳出合計") or len(amounts) != 3:
                raise ValueError(f"Unrecognized total row at page {page_number}, y={line[0]['yMin']}")
            if total is not None:
                raise ValueError(f"Duplicate expenditure total at page {page_number}")
            total = {"当初予算額": amounts[0]["text"], "補正予算額": amounts[1]["text"],
                     "計": amounts[2]["text"], "y": line[0]["yMin"]}
            continue
        match = re.fullmatch(r"(\d+)", first["text"])
        if match and first["xMin"] < 110:
            x = first["xMin"]
            level = "款" if x < 58 else "項" if x < 70 else "目"
            if len(amounts) != 3:
                raise ValueError(f"款項目 row needs 3 printed amounts at page {page_number}, y={line[0]['yMin']}")
            name = line_text([w for w in head[1:] if w["xMin"] < 410])
            record = {"level": level, "番号": match[1], "名称": name,
                      "当初予算額": amounts[0]["text"], "補正予算額": amounts[1]["text"],
                      "計": amounts[2]["text"],
                      "y_top": line[0]["yMin"], "y_bottom": max(w["yMax"] for w in line)}
            if level == "款":
                current.clear()
            elif level == "項":
                if "款" not in current:
                    raise ValueError(f"項 without 款 at page {page_number}, y={line[0]['yMin']}")
                current.pop("目", None)
            elif level == "目":
                if "款" not in current or "項" not in current:
                    raise ValueError(f"目 without 款・項 at page {page_number}, y={line[0]['yMin']}")
            if level == "項":
                record["path"] = {"款": current["款"]}
            elif level == "目":
                record["path"] = {"款": current["款"], "項": current["項"]}
            current[level] = record
            rows.append(record)
        elif match and 410 <= first["xMin"] < 426:
            if set(current) != {"款", "項", "目"}:
                raise ValueError(f"節 without 款・項・目 at page {page_number}, y={line[0]['yMin']}")
            if len(amounts) != 1:
                raise ValueError(f"節 row needs 1 printed amount at page {page_number}, y={line[0]['yMin']}")
            name = line_text(head[1:])
            if not name:
                raise ValueError(f"節 without a name at page {page_number}, y={line[0]['yMin']}")
            rows.append({"level": "節", "番号": match[1], "名称": name, "金額": amounts[0]["text"],
                         "path": dict(current),
                         "y_top": line[0]["yMin"], "y_bottom": max(w["yMax"] for w in line)})
        elif not match and not amounts:
            if not rows:
                raise ValueError(f"Continuation without a printed row at page {page_number}, y={line[0]['yMin']}")
            target = rows[-1]
            target["名称"] = target["名称"] + "\n" + line_text(head)
            target["y_bottom"] = max(target["y_bottom"], max(w["yMax"] for w in line))
        else:
            raise ValueError(f"Unrecognized left baseline at page {page_number}, y={line[0]['yMin']}:"
                             f" {[w['text'] for w in line]}")
    return rows, total


def parse_right(page_number, words):
    """Return (exec_pairs, bnodes) for one right page.

    exec_pairs are 支出済額/不用額 dicts in printed order. bnodes are 備考 flow
    nodes: ('ryuyo', ...), ('shozoku', ...), ('node', depth, ...).
    """
    text_all = "".join(w["text"] for w in words)
    for required in ("翌年度繰越額", "単位"):
        if required not in text_all:
            raise ValueError(f"Unmeasured right header at page {page_number}: missing {required}")
    if "（単位：円）" not in text_all.replace(" ", ""):
        raise ValueError(f"Unmeasured right unit at page {page_number}")
    # 備/考は大きく離して印字されるため、label baselineの構造で確認する。
    header = [ln for ln in baselines([w for w in words if w["yMin"] < 135.0])
              if any(w["text"] == "支出済額" for w in ln)]
    if len(header) != 1:
        raise ValueError(f"Unmeasured 支出済額 label at page {page_number}")
    joined = "".join(w["text"] for w in header[0])
    if "不用額" not in joined or "備" not in joined or "考" not in joined:
        raise ValueError(f"Unmeasured 不用額/備考 labels at page {page_number}: {joined!r}")
    pairs, bnodes = [], []
    for line in baselines([w for w in words if RIGHT_BODY_TOP <= w["yMin"] < RIGHT_BODY_BOTTOM]):
        for w in line:
            if not (w["xMin"] < AB_SPLIT_X or w["xMin"] >= 290.0):
                raise ValueError(f"Word inside the A/B gap at page {page_number}, y={line[0]['yMin']}")
        avals = [w for w in line if w["xMin"] < AB_SPLIT_X and AMOUNT.fullmatch(w["text"])]
        anon = [w for w in line if w["xMin"] < AB_SPLIT_X and not AMOUNT.fullmatch(w["text"])]
        bwords = [w for w in line if w["xMin"] >= AB_SPLIT_X]
        if anon:
            raise ValueError(f"Non-amount in execution columns at page {page_number}, y={line[0]['yMin']}")
        if avals and len(avals) != 2:
            raise ValueError(f"Execution baseline needs 2 printed amounts at page {page_number},"
                             f" y={line[0]['yMin']}")
        if avals:
            pairs.append({"支出済額": avals[0]["text"], "不用額": avals[1]["text"], "y": line[0]["yMin"]})
        if not bwords:
            continue
        y, yb = line[0]["yMin"], max(w["yMax"] for w in bwords)
        first_text = "".join(w["text"] for w in bwords)
        if SYOZOKU.fullmatch(first_text):
            if any(AMOUNT.fullmatch(w["text"]) for w in bwords):
                raise ValueError(f"所属 with an amount at page {page_number}, y={y}")
            bnodes.append({"kind": "shozoku", "text": first_text, "y": y, "yb": yb, "page": page_number})
            continue
        name_words, amount = split_amount_tail(bwords, page_number, y)
        name = line_text(name_words)
        if RYUYO.match(name):
            bnodes.append({"kind": "ryuyo", "text": name, "amount": amount, "y": y, "yb": yb,
                             "page": page_number})
            continue
        depth = next((i for i, (low, high) in enumerate(LEVEL_BANDS)
                      if low <= name_words[0]["xMin"] < high), None)
        if depth is None or not NUMBERED.match(name):
            raise ValueError(f"Unrecognized 備考 baseline at page {page_number}, y={y}: {name!r}")
        bnodes.append({"kind": "node", "depth": depth, "text": name, "amount": amount, "y": y, "yb": yb,
                         "page": page_number})
    return pairs, bnodes


def build_trees(bnodes):
    """Nest node/shozoku bnodes into 事業 trees. Ryuyo nodes are excluded here."""
    businesses, stack = [], []
    for node in bnodes:
        if node["kind"] == "shozoku":
            if not stack or len(stack) != 1 or stack[0]["children"]:
                raise ValueError(f"所属 without an opening 事業 at y={node['y']}")
            if stack[0]["shozoku"] is not None:
                raise ValueError(f"Duplicate 所属 at y={node['y']}")
            stack[0]["shozoku"] = node["text"]
            continue
        item = {"text": node["text"], "amount": node["amount"], "y": node["y"], "yb": node["yb"],
                "page": node["page"], "children": []}
        if node["depth"] == 0:
            stack.clear()
            businesses.append({"node": item, "shozoku": None, "children": [],
                             "open_pos": (node["page"], node["y"])})
            stack.append(businesses[-1])
        else:
            while len(stack) > node["depth"]:
                stack.pop()
            if len(stack) != node["depth"]:
                raise ValueError(f"Explanation node without observed parent at y={node['y']}:"
                                 f" {node['text']!r}")
            if node["depth"] == 1:
                stack[-1]["children"].append(item)
            else:
                stack[-1]["node"]["children"].append(item)
            stack.append({"node": item, "children": item["children"], "shozoku": None})
    for business in businesses:
        if business["shozoku"] is None:
            raise ValueError(f"事業 without 所属: {business['node']['text']!r}")
        if not business["children"]:
            raise ValueError(f"事業 without detail: {business['node']['text']!r}")
    return businesses


def leaves_of(business):
    """List root-to-leaf paths; a node with children is never a leaf."""
    paths = []

    def visit(node, path):
        here = path + [node]
        if not node["children"]:
            paths.append(here)
        else:
            for child in node["children"]:
                visit(child, here)

    for top in business["children"]:
        visit(top, [business["node"]])
    return paths


def check_subtree_sums(business):
    """Every non-leaf amount equals the sum of its children (exact, no allocation)."""
    problems = []

    def visit(node):
        if node["children"]:
            for child in node["children"]:
                visit(child)
            if _num(node["amount"]) != sum(_num(c["amount"]) for c in node["children"]):
                problems.append(f"{node['text']!r}: printed {node['amount']} != children"
                                f" {[c['amount'] for c in node['children']]}")

    visit({"text": business["node"]["text"], "amount": business["node"]["amount"],
           "children": business["children"]})
    return problems


COLUMNS = (
    ["款_番号", "款_名称", "款_当初予算額", "款_補正予算額", "款_計", "款_支出済額", "款_不用額"]
    + ["項_番号", "項_名称", "項_当初予算額", "項_補正予算額", "項_計", "項_支出済額", "項_不用額"]
    + ["目_番号", "目_名称", "目_当初予算額", "目_補正予算額", "目_計", "目_支出済額", "目_不用額", "目_備考"]
    + ["節_番号", "節_名称", "節_金額", "節_支出済額", "節_不用額"]
    + ["事業_名称", "事業_金額", "所属"]
    + ["説明1_名称", "説明1_金額", "説明2_名称", "説明2_金額", "説明3_名称", "説明3_金額"]
    + ["物理頁", "右_物理頁", "左_上端", "左_下端", "右_上端", "右_下端"]
)


def metadata_for():
    amount_cols = [c for c in COLUMNS if any(k in c for k in ("当初予算額", "補正予算額", "計", "金額", "支出済額", "不用額"))]
    note = ("後期高齢者医療特別会計の歳出事項別明細書（左右見開き）。左頁=科目・予算現額・節区分金額、"
            "右頁=支出済額・不用額（左頁明細行と同順・spread毎の系統的y差で対応）・備考フロー。"
            "備考の事業(x291)・節見出し(x299)・細目(x308)・細々目(x316)・所属・流用注記は"
            "字下げと書式で独立parseし、高さ・名称だけでは法定節へ結合しない。"
            "事業は目の執行y範囲で位置割当し、法定節対応は節番号一致+目内事業跨ぎL1金額合計"
            "==節支出済額の検証済みのみ。名称折り返しは改行結合、金額は桁区切り保持の文字列。"
            "左頁､と備考、の差は保持のまま。翌年度繰越額3細列・継続費繰越・予備費流用増減は"
            "scope内全行未印字のため不emit。単位円は右頁(単位：円）と 不用額=計−支出済額 の"
            "原典内exact一致で根拠付け。物理頁は左頁、右_物理頁は葉の備考頁"
            "（継続事業は左+1と異なる場合あり）。歳出合計は統制行として観測のみ。")
    contexts = [
        {"columns": [c for c in COLUMNS if c.startswith("款_")],
         "header_path": ["科目", "款"], "grain_columns": ["款_番号", "物理頁"]},
        {"columns": [c for c in COLUMNS if c.startswith("項_")],
         "header_path": ["科目", "項"], "grain_columns": ["款_番号", "項_番号", "物理頁"]},
        {"columns": [c for c in COLUMNS if c.startswith("目_")],
         "header_path": ["科目", "目"], "grain_columns": ["款_番号", "項_番号", "目_番号", "物理頁"]},
        {"columns": ["節_番号", "節_名称", "節_金額", "節_支出済額", "節_不用額"],
         "header_path": ["節"], "semantic_role": "setsu",
         "grain_columns": ["款_番号", "項_番号", "目_番号", "節_番号", "物理頁"]},
        {"columns": ["事業_名称", "事業_金額", "所属"],
         "header_path": ["備考", "事業"],
         "grain_columns": ["款_番号", "項_番号", "目_番号", "事業_名称"]},
        {"columns": ["説明1_名称", "説明1_金額", "説明2_名称", "説明2_金額", "説明3_名称", "説明3_金額"],
         "header_path": ["備考", "説明"],
         "grain_columns": ["款_番号", "項_番号", "目_番号", "事業_名称", "説明1_名称"]},
        {"columns": ["物理頁", "右_物理頁", "左_上端", "左_下端", "右_上端", "右_下端"],
         "header_path": ["原典参照"], "grain_columns": ["物理頁", "右_物理頁", "左_上端", "右_上端"]},
    ]
    return {"units": [{"text": "円", "scope": {"kind": "columns", "columns": amount_cols}}],
            "notes": [{"text": note, "scope": {"kind": "table"}}],
            "column_contexts": contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError("Kiyose late-elderly settlement requires one original")
    source = inputs[0]
    target = source["target"]
    if (target.get("jurisdiction") != "132217" or target.get("fiscal_year") != 2025
            or target.get("document_kind") != "settlement" or source.get("direction") != "expenditure"
            or source.get("format") != "pdf" or source.get("pdf_type") != "text"):
        raise ValueError("This measured layout is Kiyose 2025 late-elderly settlement expenditure only")
    if source.get("sha256") != ORIGIN_SHA:
        raise ValueError("Original SHA differs")
    scope = [s for s in source.get("scope", []) if s.get("account") == ACCOUNT]
    flat = sorted(p for s in scope for first, last in s["pages"] for p in range(first, last + 1))
    if flat != list(range(FIRST_PAGE, LAST_PAGE + 1)):
        raise ValueError(f"Measured scope for {ACCOUNT} must be physical pages {FIRST_PAGE}-{LAST_PAGE}")
    table_id = options["table_id"]
    destination = Path(destination)
    observations = destination / "kiyose-observations"
    observations.mkdir(parents=True, exist_ok=True)
    pages = observe(source["path"], FIRST_PAGE, LAST_PAGE, observations / "detail-bbox.html")

    problems, detail, totals = [], [], []
    spread_rows, bnodes_all, ryuyo_all = {}, [], []
    left_state: dict = {}
    for left_no in (FIRST_PAGE, FIRST_PAGE + 2, FIRST_PAGE + 4):
        right_no = left_no + 1
        rows, total = parse_left(left_no, pages[left_no], left_state)
        pairs, bnodes = parse_right(right_no, pages[right_no])
        spread_rows[left_no] = rows
        bnodes_all.extend(n for n in bnodes if n["kind"] != "ryuyo")
        ryuyo_all.extend(n for n in bnodes if n["kind"] == "ryuyo")
        if total is None:
            if len(rows) != len(pairs):
                raise ValueError(f"Left/right row count differs on spread {left_no}/{right_no}:"
                                 f" {len(rows)} != {len(pairs)}")
            detail_pairs, total_exec_pair = pairs, None
        else:
            # The trailing execution pair belongs to the 歳出合計統制行.
            if len(pairs) != len(rows) + 1:
                raise ValueError(f"Left/right row count differs on spread {left_no}/{right_no}:"
                                 f" {len(rows)} + total != {len(pairs)}")
            detail_pairs, total_exec_pair = pairs[:-1], pairs[-1]
        if rows:
            offsets = sorted(p["y"] - r["y_top"] for p, r in zip(detail_pairs, rows))
            if offsets[-1] - offsets[0] > Y_TOL:
                raise ValueError(f"Spread {left_no}/{right_no} y-offset scatters:"
                                 f" {[round(o, 2) for o in offsets]}")
        for row, pair in zip(rows, detail_pairs):
            row["支出済額"] = pair["支出済額"]
            row["不用額"] = pair["不用額"]
            row["_exec_pos"] = (right_no, pair["y"])
        if total is not None:
            totals.append({"page": left_no, **total, "exec": total_exec_pair})

        for row in rows:
            if row["level"] in ("款", "項", "目"):
                if _num(row["不用額"]) != _num(row["計"]) - _num(row["支出済額"]):
                    problems.append(f"left {left_no} {row['level']}{row['番号']}: 不用 {row['不用額']} !="
                                    f" 計−支出済 {_num(row['計']) - _num(row['支出済額'])}")
            if row["level"] == "節":
                if _num(row["不用額"]) != _num(row["金額"]) - _num(row["支出済額"]):
                    problems.append(f"left {left_no} 節{row['番号']}: 不用 {row['不用額']} != 金額−支出済")
        # 目・事業の対応と集約照合は loop 終了後の global phase で行う (事業が spread を跨ぐため)。

    # Global B-flow phase: 備考は3右頁を1つの連続フローとしてparseする
    # (事業98のようにspreadを跨ぐ継続がある)。事業→目は全局所順序で割当て、
    # 流用注記は目の header zone で割当てる。対応は番号+金額照合の検証済みのみ。
    all_rows = [(left_no, r) for left_no in sorted(spread_rows) for r in spread_rows[left_no]]
    all_moku = [(left_no, r) for left_no, r in all_rows if r["level"] == "目"]
    for _, row in all_moku:
        row["_business"] = []
        row["_memo"] = None

    businesses = build_trees(bnodes_all)
    for business in businesses:
        owner = None
        for _, m in all_moku:
            if m["_exec_pos"] <= business["open_pos"]:
                owner = m
        if owner is None:
            problems.append(f"事業 {business['node']['text']!r} before the first 目")
            continue
        owner["_business"].append(business)

    # 流用注記はB-flow上の連続run単位で割当てる (節A-baselineを跨ぐrunがあるため)。
    # run先頭が目の header zone [目A, first節A] 内にある場合のみ採用する。
    def moku_zone(row):
        idx = next(i for i, (_, r) in enumerate(all_rows) if r is row)
        following = [r for _, r in all_rows[idx + 1:]]
        first_setsu = next((r for r in following if r["level"] == "節"), None)
        if first_setsu is None:
            return None
        return (row["_exec_pos"], first_setsu["_exec_pos"])
    zones = {}
    for _, row in all_moku:
        zone = moku_zone(row)
        if zone is None:
            problems.append(f"目 without a following 節: {row['名称']!r}")
        else:
            zones[id(row)] = (row, zone)
    stream = sorted(bnodes_all + ryuyo_all, key=lambda n: (n["page"], n["y"]))
    runs, current_run = [], []
    for node in stream:
        if node["kind"] == "ryuyo":
            current_run.append(node)
        elif current_run:
            runs.append(current_run)
            current_run = []
    if current_run:
        runs.append(current_run)
    claimed = set()
    for run in runs:
        pos = (run[0]["page"], run[0]["y"])
        owner = next((row for row, (lo, hi) in zones.values() if lo <= pos <= hi), None)
        if owner is None:
            problems.append(f"流用注記 run outside 目 header zones at {pos}:"
                            f" {[n['text'] for n in run]}")
            continue
        for node in run:
            claimed.add(id(node))
            posn = (node["page"], node["y"])
            if owner["_business"] and posn >= min(b["open_pos"] for b in owner["_business"]):
                problems.append(f"流用注記 inside business block at {posn}")
                continue
            owner["_memo"] = ((owner["_memo"] + "\n" if owner["_memo"] else "")
                               + node["text"] + " " + node["amount"])
    for node in ryuyo_all:
        if id(node) not in claimed:
            problems.append(f"流用注記 outside 目 header zones at {(node['page'], node['y'])}:"
                            f" {node['text']!r}")

    for left_no, row in all_moku:
        key = (row["path"]["款"]["番号"], row["path"]["項"]["番号"], row["番号"])
        setsu = [r for _, r in all_rows if r["level"] == "節"
                 and (r["path"]["款"]["番号"], r["path"]["項"]["番号"], r["path"]["目"]["番号"]) == key]
        if not setsu:
            problems.append(f"left {left_no} 目{row['番号']} without 法定節")
        elif _num(row["計"]) != sum(_num(s["金額"]) for s in setsu):
            problems.append(f"left {left_no} 目{row['番号']}: 計 {row['計']} != Σ節")
        if not row["_business"]:
            problems.append(f"left {left_no} 目{row['番号']} without 事業")
        table = {s["番号"]: s for s in setsu}
        seen = {}
        for business in row["_business"]:
            for issue in check_subtree_sums(business):
                problems.append(f"{business['open_pos']}: {issue}")
            for top in business["children"]:
                match = NUMBERED.match(top["text"])
                if match is None or match[1] not in table:
                    problems.append(f"目{key}: L1 {top['text']!r} not a 法定節")
                    continue
                seen.setdefault(match[1], []).append(top)
        for number, section in table.items():
            if _num(section["支出済額"]) != sum(_num(t["amount"]) for t in seen.get(number, [])):
                problems.append(f"目{key} 節{number}: 節支出済 {section['支出済額']} != ΣL1")
        if row["_business"] and _num(row["支出済額"]) != sum(_num(b["node"]["amount"]) for b in row["_business"]):
            problems.append(f"目{key}: 目支出済 {row['支出済額']} != Σ事業")
        for business in row["_business"]:
            for path_nodes in leaves_of(business):
                l1 = path_nodes[1] if len(path_nodes) > 1 else None
                number = NUMBERED.match(l1["text"])[1] if l1 is not None else None
                section = table.get(number) if number else None
                if section is None:
                    problems.append(f"leaf without 法定節: {path_nodes[-1]['text']!r}")
                    continue
                levels = list(path_nodes[1:4]) + [None, None, None]
                detail.append((left_no, row, section, business, levels[:3], path_nodes[-1],
                               path_nodes[-1]["page"]))
    for _, row in all_rows:
        if row["level"] == "項":
            kids = [k for _, k in all_rows if k["level"] == "目"
                    and k["path"]["款"]["番号"] == row["path"]["款"]["番号"]
                    and k["path"]["項"]["番号"] == row["番号"]]
            if kids and _num(row["計"]) != sum(_num(k["計"]) for k in kids):
                problems.append(f"項{row['番号']}: 計 {row['計']} != Σ目")
        elif row["level"] == "款":
            kids = [k for _, k in all_rows if k["level"] == "項" and k["path"]["款"]["番号"] == row["番号"]]
            if kids and _num(row["計"]) != sum(_num(k["計"]) for k in kids):
                problems.append(f"款{row['番号']}: 計 {row['計']} != Σ項")

    if problems:
        (observations / "problems.json").write_text(json.dumps(problems, ensure_ascii=False, indent=2) + "\n")
        raise ValueError(f"{len(problems)} unconfirmed observations:\n" + "\n".join(problems[:20]))

    if len(totals) != 1:
        raise ValueError(f"Expected one printed expenditure total, found {len(totals)}")
    total = totals[0]
    kake_rows = [r for _, r in all_rows if r["level"] == "款"]
    if _num(total["計"]) != sum(_num(r["計"]) for r in kake_rows):
        raise ValueError("歳出合計計 != Σ款計")
    total_exec = total["exec"]
    if _num(total_exec["不用額"]) != _num(total["計"]) - _num(total_exec["支出済額"]):
        raise ValueError("歳出合計不用 != 計−支出済")
    if _num(total_exec["支出済額"]) != sum(_num(r["支出済額"]) for r in kake_rows):
        raise ValueError("歳出合計支出済 != Σ款支出済")
    if _num(total_exec["不用額"]) != sum(_num(r["不用額"]) for r in kake_rows):
        raise ValueError("歳出合計不用 != Σ款不用")
    (observations / "total.json").write_text(json.dumps(
        {"left": {k: v for k, v in total.items() if k != "exec"}, "right": total_exec},
        ensure_ascii=False, indent=2) + "\n")

    records = []
    for left_no, moku, section, business, levels, leaf, leaf_page in detail:
        row = {
            "款_番号": moku["path"]["款"]["番号"], "款_名称": moku["path"]["款"]["名称"],
            "款_当初予算額": moku["path"]["款"]["当初予算額"], "款_補正予算額": moku["path"]["款"]["補正予算額"],
            "款_計": moku["path"]["款"]["計"], "款_支出済額": moku["path"]["款"]["支出済額"],
            "款_不用額": moku["path"]["款"]["不用額"],
            "項_番号": moku["path"]["項"]["番号"], "項_名称": moku["path"]["項"]["名称"],
            "項_当初予算額": moku["path"]["項"]["当初予算額"], "項_補正予算額": moku["path"]["項"]["補正予算額"],
            "項_計": moku["path"]["項"]["計"], "項_支出済額": moku["path"]["項"]["支出済額"],
            "項_不用額": moku["path"]["項"]["不用額"],
            "目_番号": moku["番号"], "目_名称": moku["名称"],
            "目_当初予算額": moku["当初予算額"], "目_補正予算額": moku["補正予算額"],
            "目_計": moku["計"], "目_支出済額": moku["支出済額"], "目_不用額": moku["不用額"],
            "目_備考": moku["_memo"],
            "節_番号": section["番号"], "節_名称": section["名称"], "節_金額": section["金額"],
            "節_支出済額": section["支出済額"], "節_不用額": section["不用額"],
            "事業_名称": business["node"]["text"], "事業_金額": business["node"]["amount"],
            "所属": business["shozoku"],
            "説明1_名称": levels[0]["text"] if levels[0] else None,
            "説明1_金額": levels[0]["amount"] if levels[0] else None,
            "説明2_名称": levels[1]["text"] if levels[1] else None,
            "説明2_金額": levels[1]["amount"] if levels[1] else None,
            "説明3_名称": levels[2]["text"] if levels[2] else None,
            "説明3_金額": levels[2]["amount"] if levels[2] else None,
            "物理頁": left_no, "右_物理頁": leaf_page,
            "左_上端": section["y_top"], "左_下端": section["y_bottom"],
            "右_上端": leaf["y"], "右_下端": leaf["yb"],
        }
        records.append(row)
    if not records:
        raise ValueError("No explanation leaves in the measured scope")
    per_moku = {}
    for _, moku, _, _, _, _, _ in detail:
        key = f"{moku['path']['款']['番号']}-{moku['path']['項']['番号']}-{moku['番号']} {moku['名称'].replace(chr(10), '')}"
        per_moku[key] = per_moku.get(key, 0) + 1
    (observations / "grain.json").write_text(json.dumps(
        {"rows": len(records), "per_moku": per_moku}, ensure_ascii=False, indent=2) + "\n")
    columns = tuple(ParquetColumn(c, "BIGINT" if c in ("物理頁", "右_物理頁")
                                else "DOUBLE" if c.endswith(("上端", "下端")) else "VARCHAR")
                    for c in COLUMNS)
    output = write_conversion(destination / (table_id + ".parquet"), records, columns=columns,
                              context=ConversionContext(source["sha256"], table_id, __file__))
    from ingestion.fiscal.manifest import validate_metadata
    validate_metadata(metadata_for(), list(COLUMNS))
    return {table_id: {"path": Path(output.path), "metadata": metadata_for()}}
