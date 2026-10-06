from __future__ import annotations
import re
from collections import defaultdict
from . import _layout as L
from ._positioned import rows_of
LEVELS = ("project", "setsu", "detail")

def _span_text(line, span: tuple[float, float]) -> str:
    """その x 範囲に来た文字を左から連ねる。**汎用の列判定を通さない。**

    ⚠️ 以前は「全列を一度に切り出す」汎用の関数を通していたが、切り出した結果のうち
    実際に使うのは節のコードの1列だけで、名前と金額はどれも `_split_amount` が
    別に切り出していた。数百頁 × 各頁の行数ぶん、使わない列のために行を並べ替えていた。
    """
    return "".join(c for _, c in sorted((x, c) for x, c in line if span[0] <= x < span[1]))

def _strip_suffix(chars: list[tuple[float, str]], suffix: str) -> list[tuple[float, str]]:
    """金額に付く単位（`千円`）を落とす。**落とせなければ金額として読まない。**

    ⚠️ 単位が付く団体では、行末は数字ではなく単位で終わる。落とさずに行末から
    数字を切り出そうとすると1件も取れない。逆に、単位が付かない行
    （説明欄の自由記述にある「3,000円」「98.0％」など）は落とせないので、
    そのまま数字の切り出しに失敗して弾かれる — **単位そのものが項目の目印になる**。
    """
    if not suffix:
        return chars
    i = len(chars)
    for want in reversed(suffix):
        while i and chars[i - 1][1] in " 　":
            i -= 1
        if not i or chars[i - 1][1] != want:
            return []
        i -= 1
    return chars[:i]

def _split_amount(line, left: float, right: float,
                  suffix: str = "") -> tuple[str, str, float | None, float | None]:
    """欄を「名前」と「右揃えの金額」に割る。**境界の x では割らない。**

    表の欄はどれも名前が左寄せ・金額が右揃えなので、割り方は1つでよい。
    ⚠️ **固定の境界で割ると、欄をはみ出した行が丸ごと落ちる。** 実測で2度起きた。
      * 長い名前が金額の欄へこぼれる（昭島市 歳入 22-4-4。30,000 千円が消えた）
      * 桁の多い金額が名前の欄へこぼれる（千代田区 歳出。目の額の先頭 1 桁が欠け、
        392,119 が 4,392,119 として突合に落ちた。**30 目**で起きていた）
    どちらも「欄の幅は中身で決まるのに、宣言は紙面のどこかに線を引く」ことから来る。
    行末から数字と桁区切りだけの連なりを取れば、名前も金額もどこまで伸びても割れる。
    段の判定に使う右端も同じ文字から取る。**左端も返す** — 折返しの判定に要る。
    """
    chars = sorted((x, c) for x, c in line if left <= x < right)
    if not chars:
        return "", "", None, None
    start = chars[0][0]
    if suffix:
        stripped = _strip_suffix(chars, suffix)
        if not stripped:
            # 単位が付いていない行。名前だけとして扱う（金額の欄には数が無い）
            return "".join(c for _, c in chars), "", None, start
        chars = stripped
    i = len(chars)
    while i > 0 and chars[i - 1][1] in "0123456789,":
        i -= 1
    name = "".join(c for _, c in chars[:i])
    if i == len(chars):
        return name, "", None, start
    return name, "".join(c for _, c in chars[i:]), chars[-1][0], start

class _Nested:
    """説明欄そのものが 事業 → 節 → 細節 の入れ子になっている形（歳出）。

    ⚠️ **葉だけを行にする。** 3段は同じ金額を重複して印字しているので、
    全部を行にすると合計が3倍になる。段ごとの合計は突合が使う。
    """

    def __init__(self, levels: dict[str, float]) -> None:
        self.levels = [lv for lv in LEVELS if lv in levels]
        self.rows: list[dict] = []
        self.open: dict[str, dict | None] = dict.fromkeys(self.levels)
        self.by_level: dict[str, int] = dict.fromkeys(self.levels, 0)

    def add(self, level: str, name: str, amount: int, context: dict) -> None:
        depth = self.levels.index(level)
        self._close(depth)
        for shallower in self.levels[:depth]:
            if self.open[shallower] is not None:
                self.open[shallower]["has_child"] = True
        self.open[level] = {"name": name, "amount": amount, "has_child": False,
                            "context": dict(context)}
        self.by_level[level] += amount

    def _close(self, depth: int) -> None:
        """自分と同じか深い段を閉じる。子を持たなかったものが葉として行になる"""
        for level in reversed(self.levels[depth:]):
            node = self.open[level]
            if node is not None:
                if not node["has_child"]:
                    self._emit(level, node)
                self.open[level] = None

    def _emit(self, level: str, node: dict) -> None:
        names = dict.fromkeys(LEVELS, "")
        for shallower in self.levels[: self.levels.index(level)]:
            if self.open[shallower] is not None:
                names[shallower] = self.open[shallower]["name"]
        names[level] = node["name"]
        self.rows.append({**node["context"],
                          "project_name": names["project"],
                          # ⚠️ **説明欄の節にはコードが無い。** コードを持つのは節列のほうで、
                          # 名前で突き合わせるのは判断（名寄せ）なので core の仕事。ここでは埋めない。
                          "setsu_code": "",
                          "setsu_name": names["setsu"],
                          "detail_name": names["detail"],
                          "amount": node["amount"]})

    def flush(self) -> None:
        self._close(0)

class _UnderSetsu:
    """説明欄が節列の節の内訳になっている形（歳入）。

    節のコードと名称は節列から取れるので、説明欄の項目は節の子（細節）として1段だけ持つ。
    節に説明欄の項目が1つも付かなければ、節そのものが葉になる。
    """

    def __init__(self, levels: dict[str, float]) -> None:
        self.levels = [lv for lv in LEVELS if lv in levels]
        self.rows: list[dict] = []
        self.by_level: dict[str, int] = dict.fromkeys(self.levels, 0)
        self._setsu: dict | None = None
        self._children = 0

    def open_setsu(self, code: str, name: str, amount: int | None, context: dict) -> None:
        self.flush()
        # ⚠️ **節の区分名も次の行へ折り返す**（`交通安全対策` + `特別交付金`）。
        # 行はこの dict を参照で持ち、折返しは `extend_setsu` がここへ書き足す。
        self._setsu = {"code": code, "name": name, "amount": amount, "context": dict(context)}
        self._children = 0

    def extend_setsu(self, more: str) -> None:
        if self._setsu is not None:
            self._setsu["name"] += more

    def add(self, level: str, name: str, amount: int, context: dict) -> None:
        if self._setsu is None:
            return
        self._children += 1
        self.by_level[level] += amount
        self.rows.append({**context, "project_name": "", "setsu": self._setsu,
                          "detail_name": name, "amount": amount})

    def flush(self) -> None:
        node = self._setsu
        self._setsu = None
        if node is None or self._children or node["amount"] is None:
            return
        # 説明欄の項目が付かなかった節。**捨てずに節そのものを葉にする**（原則6）
        self.rows.append({**node["context"], "project_name": "", "setsu": node,
                          "detail_name": "", "amount": node["amount"]})

def _resolve(row: dict) -> dict:
    """名札を値へ畳む。**抽出が終わってから**やる（折返しが確定するのが行の後だから）"""
    holders = ("kan", "kou", "moku", "setsu")
    out = {k: v for k, v in row.items() if k not in holders}
    for lv in holders:
        if lv in row:
            out[f"{lv}_code"] = row[lv]["code"]
            out[f"{lv}_name"] = row[lv]["name"]
    return out

def _level_of(right_edge: float, levels: dict[str, float], tolerance: float) -> str | None:
    for name, edge in levels.items():
        if abs(right_edge - edge) <= tolerance:
            return name
    return None

class _PageChars(list):
    """Character positions plus the original Poppler word boxes for provenance."""

    def __init__(self, words: list, character_map: dict[str, str]) -> None:
        self.words = words
        self.boxes_by_y = defaultdict(list)
        for x0, y0, x1, y1, _ in words:
            self.boxes_by_y[y0].append((x0, y0, x1, y1))
        super().__init__((x0 + (x1 - x0) * i / len(text), y0,
                          character_map.get(c, c))
                         for x0, y0, x1, _, text in words if text
                         for i, c in enumerate(text))

def _location(page: list, number: int, line: list, span: tuple, ys: set) -> dict:
    """Locate the words in a cell, in original PDF points (top-left origin)."""
    boxes = [b for y in ys for b in getattr(page, "boxes_by_y", {}).get(y, [])
             if b[2] > span[0] and b[0] < span[1]]
    return {"page": number, "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                      max(b[2] for b in boxes), max(b[3] for b in boxes)]} if boxes else {}

def extract(pages: list[list], spec: dict, direction: str, tolerance: float = 1.0,
            dump: range | None = None) -> tuple[list[dict], dict, dict]:
    """見開きを1論理表として読み、葉を出現順に返す。

    `pages` は `read_pages()` の結果。戻り値は (葉の行, 目の見出し金額, 突合の材料)。
    """
    first = spec["pages"][direction][0]
    if len(pages) != spec["pages"][direction][1] - first + 1 or len(pages) % 2:
        raise ValueError(f"{direction}: incomplete spread page range")
    columns = {k: (float(lo), float(hi)) for k, (lo, hi) in spec["columns"][direction].items()}
    # ⚠️ **どの欄が左頁にあるかは団体で違う。** 昭島市は右頁に節と説明が並ぶが、
    # 千代田区は左頁に目・財源内訳・節が入り、右頁は説明欄だけである。宣言に出す。
    left = set(spec["left_page_columns"][direction])
    merged = {**{k: v for k, v in columns.items() if k in left},
              **L.shift_right_columns({k: v for k, v in columns.items() if k not in left})}
    moku_span = merged["moku"]
    setsu_span = merged["setsu"]
    setsu_code_span = merged["setsu_code"]
    exp_left, exp_right = merged["explanation"]

    style = spec["heading_style"]
    declared = spec["explanation"][direction]
    # 説明欄の金額に付く単位。**付かない団体では空**
    suffix = L.normalize(declared.get("amount_suffix", ""))
    # 説明欄の項目に通し番号が振られているか。**振る団体でだけ落とす**
    numbered = bool(declared.get("numbered", False))
    # ⚠️ **段の右端も見開き座標へ寄せる。** 宣言は頁内座標（説明欄は右頁にある）なので、
    # 列と同じだけずらさないと、どの段にも当たらず説明欄が丸ごと落ちる（実測でそうなった）。
    levels = {k: float(v) + L.RIGHT_PAGE_X for k, v in declared["levels"].items()}
    level_tolerance = float(declared["tolerance"])
    if declared["model"] == "nested":
        tree: _Nested | _UnderSetsu = _Nested(levels)
    elif declared["model"] == "under-setsu":
        tree = _UnderSetsu(levels)
    else:
        raise ValueError(f"説明欄の作り「{declared['model']}」は未定義")
    under_setsu = isinstance(tree, _UnderSetsu)

    # 科目の名札。**行はこの dict を参照で持ち、折返しはここを書き足す。**
    labels: dict[str, dict] = {lv: {"code": None, "name": ""} for lv in ("kan", "kou", "moku")}
    kan = kou = moku = None
    moku_name_open = setsu_name_open = False
    setsu_code, setsu_name = "", ""
    # 目の見出し金額と、その目の文脈。**常に対で書いて対で読む**ので1つの辞書に持つ
    # （2つに分けると、キーがずれても気づけない）。
    moku_headers: dict[tuple, dict] = {}
    setsu_totals: dict[tuple, int] = defaultdict(int)
    setsu_observations: list[dict] = []
    observed_setsu: dict | None = None
    pending_name: str | None = None
    pending_start: float = 0.0
    annotations = 0
    source_location: dict = {}

    def context() -> dict:
        # ⚠️ **名称は値ではなく名札（可変の dict）で渡す。**
        # 科目の名称は次の行へ折り返すので、見出し行の時点ではまだ完成していない。
        # 値をその場で写すと、**その目の最初の1行だけが折返し前の名前を持つ**
        # （実測で 64 件。`保健体育総` と `保健体育総務費` が同じ目に並んでいた）。
        return {"kan": labels["kan"], "kou": labels["kou"], "moku": labels["moku"],
                "source_location": source_location,
                "source_table_id": spec.get("table_id", "statement-detail"),
                "source_amount_unit": spec["source_amount_unit"]}

    for i in range(0, len(pages) - 1, 2):
        observed_setsu = None  # 次の見開きの「区分・金額」や頁番号は名称の続きではない。
        override = spec.get("page_overrides", {}).get(str(first + i), {})
        page_columns = {**columns, **{k: tuple(v) for k, v in override.get("columns", {}).items()}}
        merged = {**{k: v for k, v in page_columns.items() if k in left},
                  **L.shift_right_columns({k: v for k, v in page_columns.items() if k not in left})}
        moku_span, setsu_span = merged["moku"], merged["setsu"]
        setsu_code_span = merged["setsu_code"]
        exp_left, exp_right = merged["explanation"]
        if "explanation_levels" in override:
            levels = {k: float(v) + L.RIGHT_PAGE_X for k, v in override["explanation_levels"].items()}
        else:
            levels = {k: float(v) + L.RIGHT_PAGE_X for k, v in declared["levels"].items()}
        spread = L.merge_spread(pages[i], pages[i + 1])
        for line in rows_of(spread, tolerance):
            original_right = [(x - L.RIGHT_PAGE_X, c) for x, c in line if x >= L.RIGHT_PAGE_X]
            source_location = _location(pages[i + 1], first + i + 1, original_right,
                                        page_columns["explanation"], line.ys)
            if dump is not None and first + i in dump:
                print(f"  p{first + i} {''.join(c for _, c in sorted(line))[:200]}")
            left_text = "".join(c for x, c in sorted(line) if x < L.RIGHT_PAGE_X)

            # ⚠️ **見出しは見開きごとに再掲される。** 款・項・目の見出しは継続の見開きでも
            # そのまま印字されるので、見出しを見るたびに文脈を畳むと**継続した明細が
            # 行き場を失う**（実測: 歳入の目「22-4-4 雑入」で、継続頁の 28 件から先が
            # 丸ごと落ち、782,905 千円のうち 257,743 千円しか拾えていなかった）。
            # だから畳むのは**値が実際に変わったとき**だけにする。
            head = L.parse_kan(left_text, style)
            if head:
                if head[0] != kan:
                    observed_setsu = None
                    tree.flush()
                    kou = moku = None
                    labels["kou"] = {"code": None, "name": ""}
                    labels["moku"] = {"code": None, "name": ""}
                    moku_name_open = False
                    labels["kan"] = {"code": head[0], "name": head[1]}
                kan = head[0]
                continue
            head = L.parse_kou(left_text, style)
            if head:
                if head[0] != kou:
                    observed_setsu = None
                    tree.flush()
                    moku = None
                    labels["moku"] = {"code": None, "name": ""}
                    moku_name_open = False
                    labels["kou"] = {"code": head[0], "name": head[1]}
                kou = head[0]
                continue

            # ── 目（見出しと本年度予算額） ─────────────────────
            raw_moku, raw_moku_amount, _, _ = _split_amount(line, *moku_span)
            cell = L.normalize(raw_moku)
            moku_amount = L.read_amount(raw_moku_amount)
            if cell and not L.is_heading(cell):
                code, name = L.split_code_and_name(cell)
                if code is not None:
                    if code != moku:
                        observed_setsu = None
                        tree.flush()
                        moku, moku_name_open = code, True
                        labels["moku"] = {"code": code, "name": name}
                    else:
                        # 継続の見開きに再掲された見出し。**名称だけ受け直す**
                        # （継続側は名称を持たないことがあるので上書きしない）。
                        moku_name_open = bool(name)
                        if name:
                            labels["moku"]["name"] = name
                    if moku_amount is not None and (kan, kou, moku) not in moku_headers:
                        source_location = _location(pages[i], first + i,
                                                    [(x, c) for x, c in line if x < L.RIGHT_PAGE_X],
                                                    page_columns["moku"], line.ys)
                        moku_headers[(kan, kou, moku)] = {"amount": moku_amount,
                                                          "context": context()}
                elif name == "計":
                    # 項の合計行。目ではないので名称の折返しもここで閉じる
                    moku_name_open = False
                elif moku_name_open:
                    # ⚠️ **目の名称は次の行へ折り返す**（`社会福祉総` + `務費`）。
                    # 繋がないと実在しない科目名になり、規則が当たらないか別の科目に当たる。
                    labels["moku"]["name"] += name
            # A blank cell can be a row from the right-hand page between two
            # wrapped left-page name lines. Keep the label open until an actual
            # new heading, item or total closes it (Akishima FY2024 自転車対策費).

            # ── 節（区分の欄） ──────────────────────────────
            code_cell = L.normalize(_span_text(line, setsu_code_span))
            raw_setsu, raw_setsu_amount, _, _ = _split_amount(line, *setsu_span)
            name_cell = L.normalize(raw_setsu)
            if code_cell.isdigit() and code_cell:
                setsu_code, setsu_name, setsu_name_open = code_cell, name_cell, True
                amount = L.read_amount(raw_setsu_amount)
                if amount is not None and moku is not None:
                    setsu_totals[(kan, kou, moku)] += amount
                    page_index = i if "setsu" in left else i + 1
                    cell_line = [(x, c) for x, c in line if x < L.RIGHT_PAGE_X] \
                        if page_index == i else original_right
                    observed_setsu = {"code": code_cell, "name": name_cell}
                    location = _location(pages[page_index], first + page_index, cell_line,
                                         (min(page_columns['setsu_code'][0], page_columns['setsu'][0]),
                                          max(page_columns['setsu_code'][1], page_columns['setsu'][1])), line.ys)
                    setsu_observations.append({**context(), 'setsu': observed_setsu,
                                               'source_location': location, 'project_name': '',
                                               'detail_name': '', 'amount': amount})
                if under_setsu:
                    page_index = i if "setsu" in left else i + 1
                    cell_line = [(x, c) for x, c in line if x < L.RIGHT_PAGE_X] \
                        if page_index == i else original_right
                    source_location = _location(pages[page_index], first + page_index,
                                                cell_line, page_columns["setsu"], line.ys)
                    tree.open_setsu(setsu_code, setsu_name, amount, context())
            elif (setsu_name_open or (not under_setsu and observed_setsu is not None)) and name_cell and not L.is_heading(name_cell):
                # 節の区分名も折り返す（`交通安全対策` + `特別交付金`）
                setsu_name += name_cell
                if observed_setsu is not None:
                    page_index = i if 'setsu' in left else i + 1
                    cell_line = [(x, c) for x, c in line if x < L.RIGHT_PAGE_X] \
                        if page_index == i else original_right
                    more = _location(pages[page_index], first + page_index, cell_line,
                                     page_columns['setsu'], line.ys)
                    previous = setsu_observations[-1]['source_location']
                    if (more.get('bbox') and previous.get('bbox') and more['page'] == previous['page']
                            and 0 <= more['bbox'][1] - previous['bbox'][1] <= 25
                            and name_cell not in ['-', '区分金額']):
                        observed_setsu['name'] += name_cell
                        a, b = previous['bbox'], more['bbox']
                        previous['bbox'] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                if under_setsu:
                    tree.extend_setsu(name_cell)
            elif not name_cell:
                setsu_name_open = False

            # ── 説明欄（右頁の右側） ──────────────────────────
            source_location = _location(pages[i + 1], first + i + 1, original_right,
                                        page_columns["explanation"], line.ys)
            raw_name, raw_amount, edge, start = _split_amount(
                line, exp_left, exp_right, suffix)
            name = L.strip_item_number(raw_name) if numbered else L.normalize(raw_name)
            if L.is_heading(name):
                name = ""
            amount = L.read_amount(raw_amount)
            level = _level_of(edge, levels, level_tolerance) if edge is not None else None
            # ⚠️ **名前も次の行へ折り返す。** 説明欄には金額だけが次行へ回る行と、
            # 名前が次行へ続く行の両方がある。持ち越した名前を無条件に捨てると、
            # **項目名が途中で切れたまま配布物に出る**（実測で
            # 「母子・父子自立支援プログラム策定事業補助金(男女共同参画・女性活躍支援担」
            # のように、続きの行にあった末尾が落ちていた）。
            # ⚠️ **無条件に繋いでもいけない。** 説明欄には目ごとのリード文
            # （「〜に要する経費を計上」）や積算根拠（「均等割」「普通徴収 21,400人」）も
            # 並んでおり、繋ぐと項目名にそれらが混ざる。
            # **同じ字下げから始まる行だけを続きとみなす** — 折返しは行頭が揃い、
            # リード文や積算根拠は字下げが違う（実測で見分けが付く）。
            continues = pending_name is not None and start is not None \
                and abs(start - pending_start) <= level_tolerance
            if name and amount is not None and level:
                tree.add(level, (pending_name + name) if continues else name,
                         amount, context())
                annotations += pending_name is not None and not continues
                pending_name = None
            elif name:
                if continues:
                    pending_name += name
                else:
                    annotations += pending_name is not None
                    pending_name, pending_start = name, start
            elif amount is not None and level and pending_name is not None:
                tree.add(level, pending_name, amount, context())
                pending_name = None
    tree.flush()
    annotations += pending_name is not None

    # ⚠️ **説明欄を1行も持たない目が実在する。** 予備費は説明する内訳が無いので、
    # 説明欄が空のまま目の見出しだけが立つ。葉が出ないので、そのままだと
    # **その目の額が配布物から丸ごと消える**（実測: 昭島市 令和7年度の歳出は
    # 予備費 150,000 千円ぶん足りず、歳入と一致しなかった）。目そのものを葉にする。
    covered = {(r["kan"]["code"], r["kou"]["code"], r["moku"]["code"]) for r in tree.rows}
    bare = 0
    for key, header in moku_headers.items():
        if key in covered:
            continue
        bare += 1
        tree.rows.append({**header["context"], "project_name": "",
                          "setsu": {"code": "", "name": ""},
                          "detail_name": "", "amount": header["amount"]})
    rows = [_resolve(r) for r in tree.rows]
    return (rows,
            {key: h["amount"] for key, h in moku_headers.items()},
            {"setsu_column": dict(setsu_totals),
             "setsu_observations": [_resolve(r) for r in setsu_observations],
             "mokuWithoutExplanation": bare,
             "by_level": tree.by_level,
             "annotations": annotations})

def reconcile(rows: list[dict], moku_totals: dict, aux: dict) -> dict:
    """**抽出漏れの検査。** 様式が同じ数字を階層ごとに重複して印字していることを使う。

    2本の突合が取れる。
      1. 目ごと: 葉の合計 == 目の本年度予算額
      2. 目ごと: 節列の合計 == 目の本年度予算額（**葉とは別の経路**なので独立した証拠になる）

    ⚠️ **復元一致より弱い。** 同じ誤りが両側に入れば通る。強さの違いは証跡に書く。
    """
    by_moku: dict[tuple, int] = defaultdict(int)
    for r in rows:
        by_moku[(r["kan_code"], r["kou_code"], r["moku_code"])] += r["amount"]

    ok = 0
    for r in rows:
        key = (r["kan_code"], r["kou_code"], r["moku_code"])
        r["moku_reconciled"] = moku_totals.get(key) == by_moku[key]
        ok += r["moku_reconciled"]

    order = lambda k: tuple(str(v) for v in k)  # noqa: E731
    bad = sorted({(r["kan_code"], r["kou_code"], r["moku_code"])
                  for r in rows if not r["moku_reconciled"]}, key=order)
    setsu_bad = sorted({k for k, v in aux["setsu_column"].items() if moku_totals.get(k) != v},
                       key=order)
    return {
        "leaves": len(rows),
        "leavesReconciled": ok,
        "moku": len(by_moku),
        "mokuHeadersFound": len(moku_totals),
        "mokuNotReconciled": len(bad),
        "setsuColumnNotReconciled": len(setsu_bad),
        "setsuColumnDifferences": [{"moku": "-".join(str(k) for k in key),
                                    "printed": moku_totals.get(key),
                                    "extracted": aux["setsu_column"][key]} for key in setsu_bad],
        "explanationLevelTotals": aux["by_level"],
        "annotationsDropped": aux["annotations"],
        "mokuWithoutExplanation": aux["mokuWithoutExplanation"],
        "total": sum(r["amount"] for r in rows),
        "notReconciled": [{"moku": "-".join(str(k) for k in key),
                           "printed": moku_totals.get(key),
                           "extracted": by_moku[key]} for key in bad][:20],
    }
