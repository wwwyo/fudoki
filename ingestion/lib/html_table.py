"""HTML の表を格子へ展開する。**層に依存しない。**

OCR（GLM-OCR）は表を HTML の `<table>` で返す。列の位置は rowspan / colspan を
展開して初めて分かるので、`<td>` の出現順ではなく**格子の列番号**で読む。
展開しないと、上の行から伸びた rowspan の分だけ列がずれる
（実測: 目の行が項の列に見え、階層が1段浅く出る）。

標準ライブラリだけで組む。表の構造は tag と2つの属性しか使わないので、
パーサを足す理由が無い。
"""

from __future__ import annotations

from html.parser import HTMLParser

Cell = tuple[int, str]          # (格子の列番号, セルの文字列)
Row = tuple[str, list[Cell]]    # (行グループ, セル)


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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in ("thead", "tbody", "tfoot"):
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
            span = _int(a.get("colspan"), 1)
            rows = _int(a.get("rowspan"), 1)
            self._cell = (self._col, span)
            for i in range(span):
                self._blocked[self._col + i] = self._index + rows - 1
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._close_cell()
        elif tag in ("tr", "table"):
            self._flush_row()

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

    def _flush_row(self) -> None:
        if self._row is None:
            return
        self._close_cell()
        self.rows.append((self._section, self._row))
        self._row = None


def _int(v: str | None, default: int) -> int:
    try:
        n = int(str(v))
    except (TypeError, ValueError):
        return default
    return n if n >= 1 else default


def grid(html: str) -> list[Row]:
    """`<tr>` ごとに、行グループと、その行に実在するセル (格子の列番号, 文字列) を返す。

    ⚠️ **rowspan で塞がれた列にセルを複製しない。** 複製すると
    「この行に書いてある」と「上から伸びている」を区別できなくなり、
    金額を持つ行を数え違える。
    """
    p = _TableParser()
    p.feed(html)
    p.close()
    return p.rows
