"""HTML の表を格子へ展開する。**層に依存しない。**

OCR（GLM-OCR）は表を HTML の `<table>` で返す。列の位置は rowspan / colspan を
展開して初めて分かるので、`<td>` の出現順ではなく**格子の列番号**で読む。
展開しないと、上の行から伸びた rowspan の分だけ列がずれる
（実測: 目の行が項の列に見え、階層が1段浅く出る）。

標準ライブラリだけで組む。表の構造は tag と2つの属性しか使わないので、
パーサを足す理由が無い。

⚠️ **期待するのは「単一の、閉じた `<table>`」だけ。** それ以外は例外にする。
`llama-mtmd-cli` は `-n` の生成上限に達しても終了コード 0 で返るので、
切り捨ては呼び出し側では検出できない。切り捨てられた HTML は閉じタグを失い、
黙って解釈すると**そのページが丸ごと 0 行になって消える**（OCR は取りこぼしが
2〜4 割あるので、その中に紛れて誰も気づかない）。fudoki の取り込みの柱
「切り捨てを成功として扱わない」がそのままここに掛かる。
"""

from __future__ import annotations

from html.parser import HTMLParser

Cell = tuple[int, str]          # (格子の列番号, セルの文字列)
Row = tuple[str, list[Cell]]    # (行グループ, セル)

# rowspan / colspan の上限。HTML 標準は colspan=1000 / rowspan=65534 だが、
# この用途（決算資料の事項別明細）の実測は colspan 最大 5・rowspan 最大 8
# （狛江 R2 の p2〜p4 をページ全体で OCR した出力、2026-08-29）。
# 実際に抽出器が渡すのは切り出した2列だけなのでさらに少ない。
# ⚠️ **上限が無いと `range(span)` と `_blocked` が膨らんで止まる**
# （実測: colspan=10^7 で 0.55 秒、10^20 で 20 秒経っても返らない）。
# 実測の 8 倍の余裕を取って 64。これを超える値は表の構造ではなく壊れた生成物である。
MAX_SPAN = 64


class MalformedTable(RuntimeError):
    """OCR の出力が「単一の、閉じた `<table>`」でない。

    ⚠️ **握り潰して空を返さない。** 空は「表に行が無かった」と区別できず、
    切り捨てを成功として扱うことになる。
    """


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[Row] = []
        self._section = "tbody"
        # 列番号 → その列が塞がっている最後の行番号（rowspan の持ち越し）。
        # ⚠️ 「あと何行」で持つと、行の開始と終了のどちらで減らすかを間違える。
        # 絶対の行番号で持てば減算そのものが要らない
        self._blocked: dict[int, int] = {}
        self._row: list[Cell] | None = None
        self._index = -1
        self._col = 0
        self._buf: list[str] = []
        self._cell: tuple[int, int] | None = None   # (列番号, colspan)
        self._depth = 0                             # 開いている <table> の数
        self._tables = 0                            # 現れた <table> の総数

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self._depth += 1
            self._tables += 1
            if self._depth > 1:
                raise MalformedTable(
                    "入れ子の <table> がある。外側の行が壊れ、内側が別の行として出る")
            if self._tables > 1:
                # ⚠️ **持ち越しをリセットして2つ目以降も読む、は採らない。**
                # 期待しているのは単一の表なので、複数出た時点で
                # 「モデルが想定と違う形を返した」ほうが事実に近い。
                # 黙って読むと、前の表の rowspan が次の表へ漏れて列がずれた分だけ
                # 静かに間違った階層が出る（実測: 1つ目の表の rowspan=3 が持ち越され、
                # 2つ目の表の1行目が列 0・1 ではなく列 1・2 から始まった）
                raise MalformedTable(
                    "<table> が2つ以上ある。期待しているのは単一の表で、"
                    "複数あると前の表の rowspan が次の表へ持ち越されて列がずれる")
        elif tag in ("thead", "tbody", "tfoot"):
            # ⚠️ **行グループをまたいで rowspan を持ち越さない。** HTML の行グループは
            # 独立していて、見出しの rowspan は本体の列を塞がない。持ち越すと
            # 本体の1行目だけ列が右へずれる
            self._section = tag
            self._blocked = {}
        elif tag == "tr":
            self._flush_row()
            self._row = []
            self._index += 1
            self._col = 0
        elif tag in ("td", "th") and self._row is not None:
            self._close_cell()
            while self._blocked.get(self._col, -1) >= self._index:
                self._col += 1
            span = _span(a, "colspan")
            rows = _span(a, "rowspan")
            self._cell = (self._col, span)
            for i in range(span):
                self._blocked[self._col + i] = self._index + rows - 1
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag == "table":
            self._flush_row()
            self._depth -= 1
            if self._depth < 0:
                raise MalformedTable("対応する <table> の無い </table> がある")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._buf.append(data)

    def _close_cell(self) -> None:
        if self._cell is None or self._row is None:
            return
        col, span = self._cell
        self._row.append((col, "".join(self._buf).strip()))
        self._col = col + span
        self._cell = None
        self._buf = []

    def finish(self) -> None:
        """閉じているかを検査する。**`close()` の後に呼ぶ。**

        ⚠️ `HTMLParser.close()` は未閉鎖のタグを補完しない。閉じたかどうかは自分で見る。
        """
        if self._depth or self._row is not None or self._cell is not None:
            raise MalformedTable(
                "<table> / <tr> / <td> が閉じていない。生成上限（llama-mtmd-cli の -n）で"
                "切り捨てられた可能性がある。llama-mtmd-cli は上限に達しても終了コード 0 で"
                "返るので、ここで見ないと切り捨てが成功として通る")
        if not self._tables:
            raise MalformedTable("<table> が1つも無い")

    def _flush_row(self) -> None:
        if self._row is None:
            return
        self._close_cell()
        self.rows.append((self._section, self._row))
        self._row = None


def _span(a: dict[str, str | None], name: str) -> int:
    """rowspan / colspan。**属性が無ければ 1、あって読めなければ例外。**

    ⚠️ **異常な値を黙って 1 に丸めない。** 丸めると、モデルが壊れた出力を返したことに
    気づけないまま「たまたま動く形」の格子が出る。
    """
    if name not in a:
        return 1
    try:
        n = int(str(a[name]).strip())
    except (TypeError, ValueError):
        raise MalformedTable(f"{name} が整数ではない: {a[name]!r}") from None
    if not 1 <= n <= MAX_SPAN:
        raise MalformedTable(f"{name}={n} は範囲外（1〜{MAX_SPAN}）")
    return n


def grid(html: str) -> list[Row]:
    """`<tr>` ごとに、行グループと、その行に実在するセル (格子の列番号, 文字列) を返す。

    ⚠️ **rowspan で塞がれた列にセルを複製しない。** 複製すると
    「この行に書いてある」と「上から伸びている」を区別できなくなり、
    金額を持つ行を数え違える。
    """
    p = _TableParser()
    p.feed(html)
    p.close()
    p.finish()
    return p.rows
