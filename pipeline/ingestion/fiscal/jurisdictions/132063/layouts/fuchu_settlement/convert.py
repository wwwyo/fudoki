"""Read Fuchu City settlement expenditure spreads from Poppler word boxes.

Measured for jurisdiction 132063, 2025 settlement, 後期高齢者医療特別会計
(physical pages 50-55: three left/right spreads). The left page carries
款・項・目 headings with 予算現額 (計/当初予算額/補正予算額) and 法定節 rows
(番号/名称/金額). The right page carries 支出済額・翌年度繰越額・不用額・備考
(brief remarks, 経費内訳 blocks, 施策番号) with 執行率. Grain: one row per
statutory setsu, plus the moku row when a moku has no setsu (予備費).
経費内訳 blocks are a separate 事業-level decomposition whose membership in a
setsu is unconfirmed, so they stay inside 目_備考/目_施策番号 and never become
rows. The printed 歳出合計統制行 is an observation, not a row.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from ingestion.lib.conversion import ConversionContext, OriginReference, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"^[△\-]?[0-9]{1,3}(?:,[0-9]{3})*$|^[△\-]?[0-9]+$")
RATE = re.compile(r"^\([0-9.]+％\)$")
PAGE_WIDTH, PAGE_HEIGHT = 595.276, 841.89
BODY_TOP = 160.0
LEFT_BOTTOM = 775.0
RIGHT_BOTTOM = 765.0
ROW_TOL = 1.5
MATCH_TOL = 2.0

BUDGET_LABELS = {
    "当初予算額": "当初予算額",
    "補正予算額": "補正予算額",
    "継続費及び繰越事業費繰越額": "継続費及び繰越事業費繰越額",
    "予備費支出": "予備費支出及び流用増減",
    "予備費支出及び流用増減": "予備費支出及び流用増減",
}


def _words(pdf: Path, first: int, last: int, path: Path):
    subprocess.run(
        ["pdftotext", "-f", str(first), "-l", str(last), "-bbox-layout",
         str(pdf), str(path)], check=True)
    found = ET.parse(path).findall(".//{*}page")
    if len(found) != last - first + 1:
        raise ValueError("Incomplete Poppler page range")
    pages = {}
    for offset, page in enumerate(found):
        number = first + offset
        if abs(float(page.get("width")) - PAGE_WIDTH) > 0.5 or \
                abs(float(page.get("height")) - PAGE_HEIGHT) > 0.5:
            raise ValueError(f"Unmeasured page dimensions at {number}")
        items = []
        for w in page.findall(".//{*}word"):
            items.append({
                "text": w.text or "",
                "xMin": float(w.get("xMin")), "yMin": float(w.get("yMin")),
                "xMax": float(w.get("xMax")), "yMax": float(w.get("yMax")),
            })
        pages[number] = items
    return pages


def _lines(words, bottom):
    ordered = sorted(words, key=lambda w: (w["yMin"], w["xMin"]))
    rows = []
    for word in ordered:
        if not BODY_TOP <= word["yMin"] < bottom or not word["text"]:
            continue
        if rows and word["yMin"] - rows[-1][0]["yMin"] <= ROW_TOL:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["xMin"])
    return rows


def _join(words):
    value = ""
    previous = None
    for word in words:
        if previous is not None and word["xMin"] - previous["xMax"] > 1.0:
            value += " "
        value += word["text"]
        previous = word
    return value


def _is_amount(text):
    return bool(AMOUNT.match(text))


def _parse_amount(text):
    negative = text.startswith("△") or text.startswith("-")
    digits = text.lstrip("△-").replace(",", "")
    value = Decimal(digits)
    return -value if negative else value


def _left_rows(words):
    """Split a left page into heading starts, budget sub-lines and setsu rows."""
    rows = []
    for line in _lines(words, LEFT_BOTTOM):
        y = line[0]["yMin"]
        numbers = [w for w in line if re.fullmatch(r"[0-9]+", w["text"]) and w["xMin"] < 75]
        kei = [w for w in line if w["text"] == "計"]
        amounts = [w for w in line if _is_amount(w["text"]) and 200 <= w["xMin"] < 345]
        setsu_num = [w for w in line
                     if re.fullmatch(r"[0-9]+", w["text"]) and 330 <= w["xMin"] < 350]
        setsu_amt = [w for w in line if _is_amount(w["text"]) and 440 <= w["xMin"] < 560]
        labels = [w for w in line if w["text"] in BUDGET_LABELS or
                  w["text"] in ("当初予算額", "補正予算額")]
        if numbers and kei and amounts:
            rows.append({"kind": "heading", "y": y, "words": line,
                         "number": numbers[0], "amount": amounts[-1]})
        elif setsu_num and setsu_amt:
            left = [w for w in line if w["xMin"] < 330]
            budget_left = [w for w in left if w["text"] in BUDGET_LABELS
                           or w["text"] in ("当初予算額", "補正予算額")]
            Cont_left = [w for w in left if w["xMin"] < 205
                         and not re.fullmatch(r"[0-9]+", w["text"])]
            if budget_left or (Cont_left and any(
                    _is_amount(w["text"]) for w in left)):
                # Shared y: left band is the heading budget sub-line,
                # right band is the setsu row. Split, never swallow.
                rows.append({"kind": "sub", "y": y, "words": left})
            if len(setsu_num) > 1 or len(setsu_amt) > 1:
                raise ValueError(f"Ambiguous setsu line at y={y:.1f}")
            rows.append({"kind": "setsu", "y": y, "words": line,
                         "number": setsu_num[0], "amount": setsu_amt[0]})
        elif setsu_num and not setsu_amt:
            raise ValueError(f"Setsu number without amount at y={y:.1f} (wrapping unhandled)")
        elif labels or all(w["xMin"] < 205 and not _is_amount(w["text"]) for w in line):
            rows.append({"kind": "sub", "y": y, "words": line})
        elif _is_amount(line[-1]["text"]) and line[-1]["xMin"] >= 200 and \
                not any(w["xMin"] < 75 and re.fullmatch(r"[0-9]+", w["text"]) for w in line):
            # 歳出合計統制行 (spaced words, no hierarchy number).
            rows.append({"kind": "total", "y": y, "words": line})
        else:
            raise ValueError(f"Unclassified left line at y={y:.1f}: {_join(line)}")
    return rows


def _heading_level(number_x, last_level):
    # Bands measured on the 2025 kouki scope: kan 42.5/47.8, kou 47.8/52.1/57.0,
    # moku 57.0/61.8/66.6. A kan after setsu rows shares the kou x band, so the
    # [45.5, 50) band falls back to order (a kou directly repeats its kan).
    if number_x < 45.5:
        return "kan"
    if number_x < 50.0:
        return "kou" if last_level == "kan" else "kan"
    if number_x < 55.0:
        return "kou"
    if number_x < 60.0:
        return "kou" if last_level == "kan" else "moku"
    return "moku"


def _parse_left(pages, numbers):
    headings = []
    setsu_rows = []
    totals = []
    context = {"kan": None, "kou": None, "moku": None}
    last_level = None
    current = None
    for page in sorted(pages):
        for row in _left_rows(pages[page]):
            if row["kind"] == "total":
                totals.append({"page": page, "y": row["y"], "text": _join(row["words"])})
                current = None
                continue
            if row["kind"] == "heading":
                number = row["number"]["text"]
                name = _join([w for w in row["words"]
                              if w["xMin"] < 205 and w is not row["number"]])
                level = _heading_level(row["number"]["xMin"], last_level)
                current = {"level": level, "page": page, "y": row["y"],
                           "number": number, "name": name,
                           "計": row["amount"]["text"],
                           "当初予算額": None, "補正予算額": None,
                           "継続費及び繰越事業費繰越額": None,
                           "予備費支出及び流用増減": None,
                           "top": row["y"], "bottom": row["y"],
                           "words": list(row["words"])}
                headings.append(current)
                if level == "kan":
                    context.update(kan=current, kou=None, moku=None)
                elif level == "kou":
                    context.update(kou=current, moku=None)
                else:
                    context["moku"] = current
                last_level = level
            elif row["kind"] == "setsu":
                name = _join([w for w in row["words"]
                              if row["number"]["xMax"] < w["xMin"] < row["amount"]["xMin"]])
                entry = {"page": page, "y": row["y"],
                         "number": row["number"]["text"], "name": name,
                         "金額": row["amount"]["text"],
                         "top": row["y"], "bottom": row["words"][-1]["yMax"],
                         "bbox": row["words"]}
                setsu_rows.append(entry)
                current = None
            else:
                if current is None:
                    if totals and totals[-1]["page"] == page:
                        totals[-1]["text"] += "\n" + _join(row["words"])
                        continue
                    raise ValueError(f"Budget sub-line without heading at y={row['y']:.1f}")
                for word in row["words"]:
                    label = BUDGET_LABELS.get(word["text"])
                    if label and label in current:
                        same = [w for w in row["words"]
                                if _is_amount(w["text"]) and abs(w["yMin"] - word["yMin"]) <= ROW_TOL]
                        if not same:
                            raise ValueError(f"Budget label without amount at y={row['y']:.1f}")
                        current[label] = same[-1]["text"]
                for word in row["words"]:
                    if word["xMin"] < 205 and not re.fullmatch(r"[0-9]+", word["text"]) \
                            and word["text"] not in BUDGET_LABELS \
                            and word["text"] not in ("当初予算額", "補正予算額", "計"):
                        if word["text"] not in current["name"]:
                            current["name"] += word["text"]
                current["bottom"] = max(current["bottom"], row["y"])
                current["words"].extend(row["words"])
    _validate_tree(headings, setsu_rows)
    return headings, setsu_rows, totals


def _check_tree(headings, setsu_rows):
    """Return a list of hierarchy/arithmetic errors for the given levels."""
    errors = []
    order = {id(h): i for i, h in enumerate(headings)}
    if not headings or headings[0]["level"] != "kan":
        return ["Expenditure detail must start with a kan heading"]
    kans = [h for h in headings if h["level"] == "kan"]
    kous = [h for h in headings if h["level"] == "kou"]
    mokus = [h for h in headings if h["level"] == "moku"]
    if not kous:
        errors.append("Missing kou headings")
    if not mokus:
        errors.append("Missing moku headings")
    for moku in mokus:
        prev = [h for h in headings if order[id(h)] < order[id(moku)]]
        if not prev:
            errors.append(f"Moku without parent: {moku['number']} {moku['name']}")
            continue
        owner = prev[-1]
        if owner["level"] not in ("kou", "moku"):
            errors.append(f"Moku outside kou: {moku['number']} {moku['name']}")
        elif owner["level"] == "moku":
            kou = max([h for h in headings if h["level"] == "kou"
                       and order[id(h)] < order[id(moku)]],
                      key=lambda h: order[id(h)], default=None)
            kan_after_kou = any(h["level"] == "kan" and order[id(kou)] < order[id(h)] < order[id(moku)]
                                for h in headings) if kou is not None else True
            if kou is None or kan_after_kou:
                errors.append(f"Moku outside kou: {moku['number']} {moku['name']}")
    try:
        attached = _attach_setsu(headings, setsu_rows)
    except ValueError as exc:
        return [str(exc)]
    for moku in mokus:
        kids = attached[id(moku)]
        if kids:
            try:
                want = _parse_amount(moku["計"])
                got = sum(_parse_amount(k["金額"]) for k in kids)
            except Exception:
                errors.append(f"Unparsable moku/setusu amounts for {moku['number']} {moku['name']}")
                continue
            if want != got:
                errors.append(f"Moku-kei mismatch for {moku['number']} {moku['name']}: "
                              f"kei={moku['計']} sum={got}")
    for i, kan in enumerate(kans):
        following = [h for h in kous if order[id(h)] > order[id(kan)]
                     and (i + 1 >= len(kans) or order[id(h)] < order[id(kans[i + 1])])]
        if not following:
            errors.append(f"Kan without kou: {kan['number']} {kan['name']}")
            continue
        try:
            want = _parse_amount(kan["計"])
            got = sum(_parse_amount(h["計"]) for h in following)
        except Exception:
            errors.append(f"Unparsable kan/kou amounts for {kan['number']} {kan['name']}")
            continue
        if want != got:
            errors.append(f"Kan-kei mismatch for {kan['number']} {kan['name']}: "
                          f"kei={kan['計']} kou-sum={got}")
    for kou in kous:
        following = [h for h in mokus if order[id(h)] > order[id(kou)]]
        stop = min([order[id(h)] for h in headings
                    if order[id(h)] > order[id(kou)] and h["level"] in ("kan", "kou")] or [10 ** 12])
        mine = [h for h in following if order[id(h)] < stop]
        if not mine:
            errors.append(f"Kou without moku: {kou['number']} {kou['name']}")
            continue
        try:
            want = _parse_amount(kou["計"])
            got = sum(_parse_amount(h["計"]) for h in mine)
        except Exception:
            errors.append(f"Unparsable kou/moku amounts for {kou['number']} {kou['name']}")
            continue
        if want != got:
            errors.append(f"Kou-kei mismatch for {kou['number']} {kou['name']}: "
                          f"kei={kou['計']} moku-sum={got}")
    return errors


def _attach_setsu(headings, setsu_rows):
    attached = {id(h): [] for h in headings if h["level"] == "moku"}
    current_moku = None
    for event in sorted(headings + setsu_rows, key=lambda e: (e["page"], e["y"])):
        if event.get("level") == "moku":
            current_moku = event
        elif event.get("level") is None:
            if current_moku is None:
                raise ValueError("Setsu row before any moku heading")
            attached[id(current_moku)].append(event)
    return attached


def _validate_tree(headings, setsu_rows):
    """Check hierarchy sums, flipping a provisional kou to kan when sums prove it.

    A new kan after setsu rows can share the x band of kou numbers, so the
    provisional level may mark it kou. A flip is accepted only when the full
    tree validates afterwards; otherwise the mismatch is raised loudly.
    """
    errors = _check_tree(headings, setsu_rows)
    if not errors:
        _validate_tree._flip = None
        return None
    for candidate in [h for h in headings if h["level"] in ("kan", "kou")]:
        original = candidate["level"]
        candidate["level"] = "kou" if original == "kan" else "kan"
        retry = _check_tree(headings, setsu_rows)
        if not retry:
            _validate_tree._flip = {"number": candidate["number"],
                                    "name": candidate["name"],
                                    "from": original, "to": candidate["level"],
                                    "page": candidate["page"], "y": candidate["y"]}
            return candidate
        candidate["level"] = original
    raise ValueError("Hierarchy validation failed: " + "; ".join(errors))


def _split_notes(notes):
    """Route right-side words to a row brief or to the moku block.

    A data line can share its y with a block line (the 見出し, an 内訳 item
    first line, or the 合計 footer). Block lines are detected by: the 合計
    pair anywhere on the line, a leading item number, or a heading made only
    of single characters. Genuine briefs always contain a multi-character
    word and never start with a bare number in this scope.
    """
    rest = list(notes)
    texts = [w["text"] for w in rest]
    footer = "合" in texts and "計" in texts
    first_digits = bool(rest) and re.fullmatch(r"[0-9]+", rest[0]["text"])
    all_single = bool(rest) and all(len(w["text"]) == 1 for w in rest)
    if footer or first_digits or all_single:
        return None, rest
    return rest, None


def _parse_right(pages, order_index, totals):
    exec_rows = []
    current = None
    _parse_right._last_total = None
    for page in sorted(pages):
        for line in _lines(pages[page], RIGHT_BOTTOM):
            y = line[0]["yMin"]
            spent = [w for w in line if _is_amount(w["text"]) and w["xMin"] < 150]
            rates = [w for w in line if RATE.match(w["text"])]
            carried = [w for w in line if _is_amount(w["text"]) and 170 <= w["xMin"] < 200]
            unused = [w for w in line if _is_amount(w["text"]) and 200 <= w["xMin"] < 265]
            notes = [w for w in line if w["xMin"] >= 265]
            if spent:
                if len(spent) > 1 or len(carried) > 1 or len(unused) > 1:
                    raise ValueError(f"Ambiguous execution line at p{page} y={y:.1f}")
                match = [e for e in order_index if abs(e["y"] - y) <= MATCH_TOL
                         and e["page"] == page - 1]
                if len(match) != 1:
                    total_hit = [x for x in totals if x["page"] == page - 1
                                 and abs(x["y"] - y) <= MATCH_TOL]
                    if len(match) == 0 and len(total_hit) == 1:
                        total_hit[0]["exec"] = {
                            "spent": spent[0]["text"],
                            "carried": carried[0]["text"] if carried else None,
                            "unused": unused[0]["text"] if unused else None,
                            "rate": rates[0]["text"] if rates else None}
                        current = None
                        _parse_right._last_total = (page, y, total_hit[0])
                        continue
                    raise ValueError(f"Right line at p{page} y={y:.1f} matches "
                                     f"{len(match)} left rows")
                row = match[0]
                brief, block = _split_notes(notes)
                entry = {"row": row, "spent": spent[0]["text"],
                         "rate": rates[0]["text"] if rates else None,
                         "carried": carried[0]["text"] if carried else None,
                         "unused": unused[0]["text"] if unused else None,
                         "brief": _join(brief) if brief else None}
                exec_rows.append(entry)
                current = entry
                if block:
                    _block_append(current, block)
            elif rates and not carried and not unused and not notes:
                if current is None and getattr(_parse_right, "_last_total", None):
                    tpage, ty, tobj = _parse_right._last_total
                    if tpage == page and 0 < y - ty < 15 and len(rates) == 1:
                        tobj["exec"]["rate"] = rates[0]["text"]
                        continue
                if current is None or current["rate"] is not None:
                    raise ValueError(f"Orphan execution rate at p{page} y={y:.1f}")
                if len(rates) > 1:
                    raise ValueError(f"Ambiguous execution rate at p{page} y={y:.1f}")
                current["rate"] = rates[0]["text"]
            elif notes or rates:
                if current is None or current["row"].get("_block_owner") is None:
                    raise ValueError(f"Block line before any moku at p{page} y={y:.1f}")
                _, block = _split_notes(notes)
                _block_append(current, block if block is not None else notes)
            elif carried or unused:
                raise ValueError(f"Carry/unused without spent at p{page} y={y:.1f}")
    return exec_rows


def _block_append(entry, words):
    owner = entry["row"].get("_block_owner")
    if owner is None:
        raise ValueError("Moku block line outside any moku")
    owner["_block"].extend(words)
    for word in words:
        if word["xMin"] >= 535 and re.fullmatch(r"[0-9]+", word["text"]):
            owner["_policies"].append(word["text"])


def _block_text(owner):
    if not owner["_block"]:
        return None
    ordered = sorted(owner["_block"], key=lambda w: (w["yMin"], w["xMin"]))
    lines, current_y = [], None
    for word in ordered:
        if current_y is None or abs(word["yMin"] - current_y) > ROW_TOL:
            lines.append([])
            current_y = word["yMin"]
        lines[-1].append(word)
    return "\n".join(_join(sorted(line, key=lambda w: w["xMin"])) for line in lines)


COLUMNS = (
    ["款番号", "款名称", "款_計", "款_当初予算額", "款_補正予算額",
     "款_継続費及び繰越事業費繰越額", "款_予備費支出及び流用増減",
     "款_支出済額", "款_執行率", "款_翌年度繰越額", "款_不用額"]
    + ["項番号", "項名称", "項_計", "項_当初予算額", "項_補正予算額",
       "項_継続費及び繰越事業費繰越額", "項_予備費支出及び流用増減",
       "項_支出済額", "項_執行率", "項_翌年度繰越額", "項_不用額"]
    + ["目番号", "目名称", "目_計", "目_当初予算額", "目_補正予算額",
       "目_継続費及び繰越事業費繰越額", "目_予備費支出及び流用増減",
       "目_支出済額", "目_執行率", "目_翌年度繰越額", "目_不用額",
       "目_備考", "目_施策番号"]
    + ["節番号", "節名称", "節_金額", "節_支出済額",
       "節_翌年度繰越額", "節_不用額", "節_備考"]
    + ["unit", "物理頁", "bbox"]
)

AMOUNT_COLUMNS = [c for c in COLUMNS if any(
    k in c for k in ("計", "予算額", "繰越", "流用", "金額", "支出済額", "不用額"))]


def _level_block(prefix, node, executed):
    if node is None:
        return [None] * 11
    return [node["number"], node["name"], node["計"], node["当初予算額"],
            node["補正予算額"], node["継続費及び繰越事業費繰越額"],
            node["予備費支出及び流用増減"], executed["spent"], executed["rate"],
            executed["carried"], executed["unused"]]


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError("Fuchu settlement reader needs one original")
    source = inputs[0]
    target = source["target"]
    if (target["jurisdiction"] != "132063" or target["document_kind"] != "settlement"
            or source["direction"] != "expenditure" or source["format"] != "pdf"
            or source.get("pdf_type") != "text"):
        raise ValueError("This measured layout is Fuchu 2025 settlement expenditure only")
    account = options.get("account", "後期高齢者医療特別会計")
    selected = [p for scope in source["scope"] if scope["account"] == account
                for first, last in scope["pages"] for p in range(first, last + 1)]
    if not selected or sorted(selected) != list(range(selected[0], selected[-1] + 1)):
        raise ValueError(f"Measured scope for {account} must be one contiguous page range")
    if len(selected) % 2:
        raise ValueError(f"Detail pages for {account} must pair into left/right spreads")
    table_id = options["table_id"]
    destination = Path(destination)
    pdf = Path(source["path"])
    with tempfile.TemporaryDirectory() as workdir:
        left_xml = Path(workdir) / "left.xml"
        right_xml = Path(workdir) / "right.xml"
        left = {}
        right = {}
        for index in range(0, len(selected), 2):
            left.update(_words(pdf, selected[index], selected[index], left_xml))
            right.update(_words(pdf, selected[index + 1], selected[index + 1], right_xml))
    headings, setsu, totals = _parse_left(left, selected)
    for heading in headings:
        heading["kind"] = "heading"
    attached = _attach_setsu(headings, setsu)
    kan_of, kou_of, moku_of = {}, {}, {}
    last_kan = last_kou = None
    for heading in headings:
        if heading["level"] == "kan":
            last_kan, last_kou = heading, None
        elif heading["level"] == "kou":
            last_kou = heading
        kan_of[id(heading)], kou_of[id(heading)] = last_kan, last_kou
        if heading["level"] == "moku":
            moku_of[id(heading)] = heading
            heading["_block"], heading["_policies"] = [], []
            heading["_block_owner"] = heading
    for moku_id, kids in attached.items():
        for kid in kids:
            kid["kind"] = "setsu"
            for index, heading in enumerate(headings):
                if id(heading) == moku_id:
                    break
            kid["_block_owner"] = next(h for h in headings if id(h) == moku_id)
            prev = [h for h in headings if (h["page"], h["y"]) < (kid["page"], kid["y"])]
            kan = next((h for h in reversed(prev) if h["level"] == "kan"), None)
            kou = next((h for h in reversed(prev) if h["level"] == "kou"), None)
            moku = next((h for h in reversed(prev) if h["level"] == "moku"), None)
            kid["_kan"], kid["_kou"], kid["_moku"] = kan, kou, moku
    order_index = headings + setsu
    exec_rows = _parse_right(right, order_index, totals)
    by_id = {id(r["row"]): r for r in exec_rows}
    if len(by_id) != len(order_index):
        missing = [f"{getattr(r, 'get', lambda k: '?')('number')}" for r in order_index
                   if id(r) not in by_id]
        raise ValueError(f"Execution match incomplete, missing {len(missing)} rows")
    rows = []
    for moku in [h for h in headings if h["level"] == "moku"]:
        kids = attached[id(moku)]
        executed_moku = by_id[id(moku)]
        block = _block_text(moku)
        policies = ",".join(moku["_policies"]) if moku["_policies"] else None
        if executed_moku["brief"] and block:
            moku_remarks = executed_moku["brief"] + "\n" + block
        else:
            moku_remarks = executed_moku["brief"] or block
        if not kids:
            rows.append(_emit_row(moku, None, kan_of[id(moku)], kou_of[id(moku)], moku,
                                  by_id, executed_moku, moku_remarks, policies))
        for kid in kids:
            rows.append(_emit_row(kid, kid, kid["_kan"], kid["_kou"], kid["_moku"],
                                  by_id, executed_moku, moku_remarks, policies))
    result_dir = destination / table_id
    context = ConversionContext(
        origin_id=source.get("sha256", target["jurisdiction"]),
        table_id=table_id,
        extractor_ref="pipeline/ingestion/fiscal/jurisdictions/132063/layouts/"
                      "fuchu_settlement/convert.py",
        layout_ref="132063 fuchu_settlement (measured p50-55)",
        selection_ref="pipeline/source_selection/132063.json#2025/settlement",
        origins=(OriginReference(bucket="fudoki-inputs",
                                 key="fiscal/source-selection/132063/2025/settlement-2.pdf",
                                 sha256=source.get("sha256", "0" * 64),
                                 bytes=Path(source["path"]).stat().st_size),),
    )
    columns = tuple(ParquetColumn(name, "BIGINT" if name == "物理頁" else "VARCHAR")
                    for name in COLUMNS)
    result = write_conversion(result_dir / f"{table_id}.parquet", rows,
                              columns=columns, context=context)
    metadata = {"units": [{"text": "円", "scope": {"kind": "columns",
                                                  "columns": AMOUNT_COLUMNS}}],
                "notes": [{"text": "法定節が行。節を持たない25款5項5目予備費は目行。款・項・目の金額・執行額は所属contextとして各行へ反復。右頁備考の経費内訳ブロック（見出し・項目・合計）は事業別の分解で節対応未確認のため行化せず、属する目の目_備考へ印字行の改行のまま保持。末尾の施策番号は目_施策番号へカンマ結合で保持し、目_備考の行内にも残る。歳出合計統制行は行化せずlocal観測。執行率は原典の百分率表記を保持。継続費繰越・予備費流用欄は対象範囲で印字なしのため全行NULL。物理頁は左頁、bboxは左頁の行bounds。",
                             "scope": {"kind": "table"}}]}
    observations = {"flipped_to_kan": getattr(_validate_tree, "_flip", "unknown"),
                    "printed_total": totals,
                    "row_count": len(rows)}
    (result_dir / "observations.json").write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n")
    return {table_id: {"path": Path(result.path), "metadata": metadata}}


def _emit_row(owner, setsu, kan, kou, moku, by_id, executed_moku, remarks, policies):
    kan_exec = by_id[id(kan)] if kan is not None and id(kan) in by_id else None
    kou_exec = by_id[id(kou)] if kou is not None and id(kou) in by_id else None
    own_exec = by_id[id(owner)]
    if kan is None or kou is None or moku is None:
        raise ValueError("Detail row without full kan/kou/moku context")
    row = {}
    row.update(dict(zip(
        COLUMNS[0:11],
        _level_block("款", kan, {"spent": kan_exec["spent"] if kan_exec else None,
                                 "rate": kan_exec["rate"] if kan_exec else None,
                                 "carried": kan_exec["carried"] if kan_exec else None,
                                 "unused": kan_exec["unused"] if kan_exec else None}))))
    row.update(dict(zip(
        COLUMNS[11:22],
        _level_block("項", kou, {"spent": kou_exec["spent"] if kou_exec else None,
                                 "rate": kou_exec["rate"] if kou_exec else None,
                                 "carried": kou_exec["carried"] if kou_exec else None,
                                 "unused": kou_exec["unused"] if kou_exec else None}))))
    moku_part = [moku["number"], moku["name"], moku["計"], moku["当初予算額"],
                 moku["補正予算額"], moku["継続費及び繰越事業費繰越額"],
                 moku["予備費支出及び流用増減"], executed_moku["spent"],
                 executed_moku["rate"], executed_moku["carried"],
                 executed_moku["unused"], remarks, policies]
    row.update(dict(zip(COLUMNS[22:35], moku_part)))
    if setsu is None:
        row.update(dict(zip(COLUMNS[35:42], [None] * 7)))
    else:
        row.update(dict(zip(COLUMNS[35:42],
                            [setsu["number"], setsu["name"], setsu["金額"],
                             own_exec["spent"], own_exec["carried"],
                             own_exec["unused"], own_exec["brief"]])))
    xs = [w["xMin"] for w in owner.get("bbox", [])] or [0.0]
    xe = [w["xMax"] for w in owner.get("bbox", [])] or [0.0]
    row.update({"unit": "円", "物理頁": owner["page"],
                "bbox": f"{min(xs):.1f},{owner['top']:.1f},{max(xe):.1f},"
                        f"{owner.get('bottom', owner['top']):.1f}"})
    return row
