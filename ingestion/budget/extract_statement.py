"""歳入歳出予算事項別明細書（PDF）を原典として取り込む。

**なぜ要るか。** 東京62団体のうち59団体は事業単位の資料を PDF でしか出していない
（2026-08-30 実測。節まで届いた資料87本はすべて PDF で、カタログの CSV で事業単位に
届くのは既収録の3団体だけ）。CSV を背骨にした取得器では1団体も足せない。

**何を落とすか。** 説明欄の葉（目 → 事業 → 節 → 細節）を1行にした表を、
`data/budget/raw/` の取得 partition へ Parquet で置く。**列は原典 CSV と同じ形**にしてあり、
staging 以降（`budget_staging` マクロと既存の検査）はそのまま効く。

⚠️ **PDF そのものは保存しない。** 再配布 stance は allow 2 / review 46 / deny 11 で、
原文を置ける団体が例外の側にある。落とすのは抽出した事実だけで、原典のバイト列は
毎回取得元から取る（証跡に URL・SHA-256・取得時刻が残るので、いつ時点のどのバイト列から
起こしたかは追える）。狛江市の `raw_form = "extracted"` と同じ扱い。

⚠️ **「無加工」を主張しない。** レイアウトから表を起こす操作は不可逆で、CSV の取り込みが
やっている復元一致の検査ができない。代わりに、様式が同じ数字を階層ごとに重複して
印字していることを使って3重に突き合わせる（`reconcile`）。復元一致より弱い。

## 組版の宣言

列の**意味**は法定様式が決めるので共有（`statement_layout.py`）、**座標**は団体ごとに違うので
宣言（`sources.toml` の `[statement]`）。原則5の切り分けそのもの。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from collections import defaultdict

from ingestion.budget import statement_layout as L
from ingestion.budget.sources import load_statements
from ingestion.lib.http import http_get
from ingestion.lib.pdf import chars_of, rows_of

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "budget" / "raw"
# 抽出器の版。**出力を変える修正をしたら上げる。**
# (PDF の SHA-256, この版) で出力が決まる、という再現性の主張がここに乗る。
EXTRACTOR_VERSION = "5"

# 説明欄の段。**入れ子の深さの名前**であって、団体ごとの語彙ではない。
# 浅い順に並べる（`nested` は3段とも使い、`under-setsu` は最も深い1段だけを使う）。
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


def read_pages(pdf: pathlib.Path, spec: dict, direction: str) -> list[list]:
    """PDF の文字と座標を読む。**行のまとめ方に依存しないので、1回読めば使い回せる。**

    ⚠️ **`extract()` の中で読まない。** 行のまとめ方（`tolerance`）を変えて2回抽出するので、
    中で読むと `pdftotext` が direction ごとに2回、資料1本あたり4回走る
    （事項別明細書は数百頁あり、そのぶん丸ごと無駄になる）。
    """
    first, last = spec["pages"][direction]
    return list(chars_of(pdf, first, last))


def extract(pages: list[list], spec: dict, direction: str, tolerance: float = 1.0,
            dump: range | None = None) -> tuple[list[dict], dict, dict]:
    """見開きを1論理表として読み、葉を出現順に返す。

    `pages` は `read_pages()` の結果。戻り値は (葉の行, 目の見出し金額, 突合の材料)。
    """
    first = spec["pages"][direction][0]
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
    pending_name: str | None = None
    pending_start: float = 0.0
    annotations = 0

    def context() -> dict:
        # ⚠️ **名称は値ではなく名札（可変の dict）で渡す。**
        # 科目の名称は次の行へ折り返すので、見出し行の時点ではまだ完成していない。
        # 値をその場で写すと、**その目の最初の1行だけが折返し前の名前を持つ**
        # （実測で 64 件。`保健体育総` と `保健体育総務費` が同じ目に並んでいた）。
        return {"kan": labels["kan"], "kou": labels["kou"], "moku": labels["moku"]}

    for i in range(0, len(pages) - 1, 2):
        spread = L.merge_spread(pages[i], pages[i + 1])
        for line in rows_of(spread, tolerance):
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
                        moku_headers[(kan, kou, moku)] = {"amount": moku_amount,
                                                          "context": context()}
                elif name == "計":
                    # 項の合計行。目ではないので名称の折返しもここで閉じる
                    moku_name_open = False
                elif moku_name_open:
                    # ⚠️ **目の名称は次の行へ折り返す**（`社会福祉総` + `務費`）。
                    # 繋がないと実在しない科目名になり、規則が当たらないか別の科目に当たる。
                    labels["moku"]["name"] += name
            elif not cell and moku_name_open and moku_amount is None:
                moku_name_open = False

            # ── 節（区分の欄） ──────────────────────────────
            code_cell = L.normalize(_span_text(line, setsu_code_span))
            raw_setsu, raw_setsu_amount, _, _ = _split_amount(line, *setsu_span)
            name_cell = L.normalize(raw_setsu)
            if code_cell.isdigit() and code_cell:
                setsu_code, setsu_name, setsu_name_open = code_cell, name_cell, True
                amount = L.read_amount(raw_setsu_amount)
                if amount is not None and moku is not None:
                    setsu_totals[(kan, kou, moku)] += amount
                if under_setsu:
                    tree.open_setsu(setsu_code, setsu_name, amount, context())
            elif setsu_name_open and name_cell and not L.is_heading(name_cell):
                # 節の区分名も折り返す（`交通安全対策` + `特別交付金`）
                setsu_name += name_cell
                if under_setsu:
                    tree.extend_setsu(name_cell)
            elif not name_cell:
                setsu_name_open = False

            # ── 説明欄（右頁の右側） ──────────────────────────
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
        "explanationLevelTotals": aux["by_level"],
        "annotationsDropped": aux["annotations"],
        "mokuWithoutExplanation": aux["mokuWithoutExplanation"],
        "total": sum(r["amount"] for r in rows),
        "notReconciled": [{"moku": "-".join(str(k) for k in key),
                           "printed": moku_totals.get(key),
                           "extracted": by_moku[key]} for key in bad][:20],
    }


# 抽出結果の列。**原典 CSV と同じ形にする**（`budget_staging` 以降がそのまま効く）。
#
# ⚠️ **direction でも団体でも同じ列にする。** 説明欄の作りは団体ごとに違い
# （昭島市の歳出は 事業→節→細節、歳入は 節→説明、千代田区は 事業→内訳）、
# 埋まる列がそのぶん変わる。だが**列そのものを団体ごとに変えると、
# 抽出器が団体の数だけスキーマを持つことになる**（`read_parquet` の glob も割れる）。
# どの段が使われるかは `dbt_project.yml` の `budget_levels` が団体 × direction で宣言し、
# 使われない段は空文字で残す（狛江市が原典の未使用階層を宣言から落とさないのと同じ理由）。
#
#   事業名     説明欄の第1段
#   節 / 節名称  その行が属する節。**出所がモデルで違う** —
#              説明欄の中に節が現れる形（昭島市の歳出）ではコードが無く、
#              節の欄が目の内訳になっている形（昭島市の歳入）ではコードが取れる
#   内訳名称    説明欄の最も深い段
COLUMNS: list[tuple[str, str]] = [
    ("款", "kan_code"), ("款名称", "kan_name"),
    ("項", "kou_code"), ("項名称", "kou_name"),
    ("目", "moku_code"), ("目名称", "moku_name"),
    ("事業名", "project_name"),
    ("節", "setsu_code"), ("節名称", "setsu_name"),
    ("内訳名称", "detail_name"),
]
AMOUNT_COLUMN = "本年度予算額"


def _write(out_dir: pathlib.Path, direction: str, fund_label: str, rows: list[dict]) -> None:
    import duckdb  # noqa: PLC0415  (抽出だけしたいときに import させない)

    columns = COLUMNS
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    decl = ", ".join(f'"{name}" VARCHAR' for name, _ in columns)
    con.execute(f'CREATE TABLE t (source_row BIGINT, "会計名称" VARCHAR, {decl}, '
                f'"{AMOUNT_COLUMN}" VARCHAR, reconciled BOOLEAN)')
    placeholders = ", ".join("?" * (len(columns) + 4))
    con.executemany(
        f"INSERT INTO t VALUES ({placeholders})",
        [(i + 1, fund_label, *(r[key] or "" for _, key in columns),
          str(r["amount"]), r["moku_reconciled"]) for i, r in enumerate(rows)])
    con.execute(f"COPY (SELECT * FROM t ORDER BY source_row) TO '{out_dir / 'data.parquet'}' "
                f"(FORMAT parquet, COMPRESSION zstd)")
    con.close()


def ingest(key: str, *, force: bool = False) -> None:
    spec = load_statements()[key]
    code, year = key.split(":")
    got = http_get(spec["url"])
    if got.status != 200:
        raise RuntimeError(f"HTTP {got.status}: {spec['url']}")

    out_dirs = {
        direction: (RAW / f"jurisdiction={code}" / f"year={year}"
                    / f"phase={spec['phase_id']}" / f"direction={direction}")
        for direction in sorted(spec["pages"])
    }
    # ⚠️ **冪等にする。抽出の前に決める。** 原典の SHA-256 と抽出器の版が同じなら何もしない。
    # 事項別明細書は 469 頁あり、両 direction の抽出に数十秒かかる。走らせてから
    # 判定すると `fetched_at` だけが動いて作業ツリーが毎回汚れ、
    # 「再生成しても同じか」を見る CI の判定が意味を失う。
    if not force and all((d / "provenance.json").exists() and (d / "data.parquet").exists()
                         for d in out_dirs.values()):
        old = [json.loads((d / "provenance.json").read_text()) for d in out_dirs.values()]
        if all(o.get("sha256") == got.sha256
               and o.get("extractor", "").endswith(f"@{EXTRACTOR_VERSION}") for o in old):
            print(f"skip  {key}  同じ原典・同じ抽出器の版で既に抽出済み")
            return

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(got.body)
        tmp = pathlib.Path(f.name)
    try:
        for direction, out_dir in out_dirs.items():
            # **文字の読み取りは1回だけ。** 下で許容幅を変えて2回抽出するが、
            # 読み取り自体は許容幅に依存しないので使い回す。
            pages = read_pages(tmp, spec, direction)
            rows, totals, aux = extract(pages, spec, direction)
            # ⚠️ **行のまとめ方に結果が依存していないことを確かめる。**
            # y の許容幅を変えて葉が変われば、抽出が行の境界に乗っている。
            # 金額は動かないことがあるので、合計突合だけでは検出できない。
            alt, _, _ = extract(pages, spec, direction, tolerance=2.0)
            summary = reconcile(rows, totals, aux)
            unstable = [a for a, b in zip(rows, alt, strict=False)
                        if (a["project_name"], a["setsu_name"], a["detail_name"])
                        != (b["project_name"], b["setsu_name"], b["detail_name"])]
            summary["nameStable"] = len(rows) == len(alt) and not unstable
            if not rows:
                raise RuntimeError(f"{key}/{direction}: 1行も抽出できなかった")
            if not summary["nameStable"]:
                raise RuntimeError(
                    f"{key}/{direction}: 行のまとめ方を変えると名称が変わる（{len(unstable)} 件）。"
                    f"抽出が行の境界に乗っている: "
                    f"{[u['detail_name'] for u in unstable[:5]]}")
            # ⚠️ **1つも突合できないのはレイアウトを読み違えている合図。**
            # 一部が落ちるのは目ごとに印を付けて下流へ渡す（原則6）が、全滅なら止める。
            if summary["leavesReconciled"] == 0:
                raise RuntimeError(
                    f"{key}/{direction}: 目の合計と1件も突合できなかった。"
                    f"抽出器がレイアウトを読めていない")
            # ⚠️ **節の欄との突合は「独立した証拠」として数えているので、落ちたら止める。**
            # 計算だけして通すと、証跡が verification に書いている保証が実際には
            # 成立していない状態で配ることになる（葉の合計がたまたま合っていても、
            # 別経路が合わないなら欄の読み方をどちらか間違えている）。
            # 正当に一致しない団体が出たら、目ごとの印（`moku_reconciled` と同じ形）へ
            # 落として下流へ渡す形に変えること — 黙って通す形には戻さない。
            if summary["setsuColumnNotReconciled"]:
                raise RuntimeError(
                    f"{key}/{direction}: 節の欄の合計が目の額と一致しない目が "
                    f"{summary['setsuColumnNotReconciled']} 件ある。"
                    f"葉の合計とは別経路なので、どちらかの欄の読み方が誤っている")
            _write(out_dir, direction, spec["fund_label"], rows)
            (out_dir / "provenance.json").write_text(json.dumps({
                "jurisdiction_code": code,
                "fiscal_year": int(year),
                "direction": direction,
                "document_title": spec["document_title"],
                # ⚠️ **取得器（CSV）と同じキーで名乗る。** 系統の図も配布物の出典も
                # 証跡を1つの形として読むので、経路ごとに項目名を変えると
                # 片方だけが黙って空欄になる（実際に報告の生成が落ちた）。
                # カタログを引いていないので `dataset_title` は無く、資料の名前が資源の名前になる。
                "dataset_title": None,
                "resource_name": spec["document_title"],
                "landing_page": spec["landing_page"],
                "resource_url_declared": True,
                "resource_url_basis": spec["url_basis"],
                "fiscal_year_basis":
                    "sources.toml が宣言した URL（カタログへの登録が存在しない）。"
                    "年度は取得元ページの見出しとリンクテキストを人が読んで決めており、"
                    "機械は照合していない。根拠は resource_url_basis にある",
                "fund_basis": spec["fund_basis"],
                "request_url": got.url,
                "status": got.status,
                "bytes": len(got.body),
                "sha256": got.sha256,
                "fetched_at": got.fetched_at,
                "pages": spec["pages"][direction],
                "layout": spec["layout"],
                "extractor": f"ingestion/budget/extract_statement.py@{EXTRACTOR_VERSION}",
                # ⚠️ **CSV の取り込みと保証の強さが違う。** 復元一致は成立しない。
                "verification": "hierarchy-totals + setsu-column-totals + name-stability",
                "verification_note":
                    "PDF のバイト列は保存していない（大半の団体で再配布の判断が付かないため、"
                    "経路を団体で分けない）。無加工であることは検査できないので、"
                    "目の見出し金額との突合・節列との突合・行のまとめ方への非依存で縛る",
                "roundtrip_verified": False,
                # ⚠️ **桁区切りは落としている。** 紙に印字された `25,450` を数として持つには
                # 外すしかない（下流は cast(... as bigint) する）。値は変えていない。
                "normalization": ["桁区切りのカンマを除去", "NFKC 正規化と空白の除去",
                                  *(["説明欄の項目の通し番号を除去（並びは source_row が保つ）"]
                                    if any(spec["explanation"][d].get("numbered")
                                           for d in spec["pages"]) else [])],
                "source_amount_unit": spec["source_amount_unit"],
                # 抽出した表の列と行数。**原典 CSV の証跡と同じ意味**（配ったものの形）。
                "header": ["source_row", "会計名称",
                           *(name for name, _ in COLUMNS),
                           AMOUNT_COLUMN, "reconciled"],
                "rows": summary["leaves"],
                "extracted": summary,
                "raw_form": spec["raw_form"],
                "redistribute": spec["redistribute"],
                "redistribute_basis": spec["redistribute_basis"],
                "license_id": spec["license_id"],
                "attribution": spec["attribution"],
            }, ensure_ascii=False, indent=2) + "\n")
            print(f"ok    {key}/{direction}  {summary['leaves']} 行  "
                  f"{summary['moku']} 目（突合できず {summary['mokuNotReconciled']}）  "
                  f"合計 {summary['total']:,}  sha256={got.sha256[:16]}…")
    finally:
        tmp.unlink(missing_ok=True)      # **PDF は残さない**


if __name__ == "__main__":
    keys = [a for a in sys.argv[1:] if not a.startswith("-")] or sorted(load_statements())
    for k in keys:
        print(f"--- {k}")
        ingest(k, force="--force" in sys.argv)
