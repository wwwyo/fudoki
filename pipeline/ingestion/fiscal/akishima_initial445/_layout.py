"""事項別明細書（法定様式）の読み取り。**列の意味は法定なので共有する。**

⚠️ **共有するのは列の意味だけで、組版は共有しない。** 地方自治法施行規則の様式が
款・項・目・節・説明という列を定めているので、どの団体の事項別明細書も同じ語彙で並ぶ。
一方で、その列が紙のどこに来るか（x 範囲）・見開きに割るか1頁に収めるかは団体ごとに違う。
だから**意味はここ（コード）、座標は宣言（sources.toml）**に置く。
パーサ設計の原則5「例外は一般化せず、その対象に閉じる」の、共有側と個体差側の切り分け。

## 見開き

昭島市の予算説明書は1つの論理行が**2頁にまたがる**。偶数頁が左（款・項・目・本年度予算額・
財源内訳）、奇数頁が右（節の区分・金額・説明欄）で、同じ y に並ぶものが同じ行である。
だから2頁の文字を1つの座標系へ合わせてから行にまとめる（右頁の x に `RIGHT_PAGE_X` を足す）。
⚠️ **頁ごとに行へまとめてから突き合わせない** — 左頁で名称が2行に折り返し、
右頁は1行、という行数の食い違いが普通に起きるので、行番号では対応が取れない。

## 説明欄の段

説明欄は3段の入れ子（事業 → 節 → 細節）で、**段は金額の右端 x が決める**。
⚠️ **名前の左端では決められない。** 名前は段ごとに字下げされるが、長い名前は
下の段の字下げ位置を越えて右へ伸びる（実測で細節の名前が x=458 まで来る）。
金額は右揃えなので、段ごとに右端が固定される（実測 530 / 522 / 504）。
"""

from __future__ import annotations

import re
import unicodedata

# 右頁の文字をずらす量。**紙幅ではなく「左頁の列に絶対に重ならない値」**でよい。
# 実際の紙幅（A4 の 595.32pt）にすると、宣言に書く右頁の x が頁内座標なのか
# 見開き座標なのかを読み手が区別できなくなる。宣言は常に頁内座標で書き、ここで足す。
RIGHT_PAGE_X = 1000.0

# 款・項の見出しの記法。**様式は文言を固定していないので団体で割れる。**
# 実測（2026-08-30）: 昭島市は `第 １ 款 民生費`、千代田区は `（款） 1 議会費`。
# ⚠️ **両方を無条件に試さない。** 片方の記法しか使わない団体で、もう片方に
# たまたま当たる行が来たときに気づけない。宣言（`heading_style`）で選ばせる。
# 全角数字も来るので NFKC で寄せてから読む。
HEADING_STYLES = {
    # 第 １ 款 民生費
    "dai": (re.compile(r"^第\s*([0-9]+)\s*款(.*)$"), re.compile(r"^第\s*([0-9]+)\s*項(.*)$")),
    # （款） 1 議会費
    "paren": (re.compile(r"^[（(]款[）)]\s*([0-9]+)(.*)$"), re.compile(r"^[（(]項[）)]\s*([0-9]+)(.*)$")),
}
_CODE_HEAD = re.compile(r"^([0-9]+)(.*)$")
_AMOUNT = re.compile(r"^[0-9,]*[0-9][0-9,]*$")

# 表の見出しと欄外。**行として読まない。**
# ⚠️ 資料名ではなく中身で弾く（原則3）。ここに並ぶのは様式が定める見出し語そのもの。
HEADINGS = {
    "目", "節", "説明", "区分", "金額", "千円", "本年度予算額", "前年度予算額", "比較",
    "特定財源", "一般財源", "国都支出金", "地方債", "その他", "本年度予算額の財源内訳",
}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace(" ", "").replace("　", "")


def merge_spread(left: list, right: list) -> list:
    """見開きの2頁を1つの座標系へ。右頁の x をずらすだけで、y はそのまま使う"""
    return list(left) + [(x + RIGHT_PAGE_X, y, c) for x, y, c in right]


def shift_right_columns(columns: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """宣言（頁内座標）を見開き座標へ。右頁の列だけを RIGHT_PAGE_X ぶんずらす"""
    return {k: (lo + RIGHT_PAGE_X, hi + RIGHT_PAGE_X) for k, (lo, hi) in columns.items()}


def read_amount(text: str) -> int | None:
    """印字された金額を読む。**桁区切りは落とす。**

    ⚠️ **これは正規化である。** 原典 CSV の取り込みはセルを一切触らないが、
    紙に印字された `25,450` を数として持つには区切りを外すしかない（下流は
    `cast(... as bigint)` する）。落としているのは表示上の区切りだけで、
    値は変わらない。証跡（`normalization`）に明記する。
    """
    t = normalize(text)
    if not t or not _AMOUNT.match(t):
        return None
    return int(t.replace(",", ""))


def split_code_and_name(text: str) -> tuple[str | None, str]:
    """`2障害者自立` のような見出しをコードと名称に割る。数字で始まらなければコードは無い"""
    t = normalize(text)
    m = _CODE_HEAD.match(t)
    if not m:
        return None, t
    return m[1], m[2]


def parse_kan(text: str, style: str) -> tuple[str, str] | None:
    m = HEADING_STYLES[style][0].match(normalize(text))
    return (m[1], m[2]) if m else None


def parse_kou(text: str, style: str) -> tuple[str, str] | None:
    m = HEADING_STYLES[style][1].match(normalize(text))
    return (m[1], m[2]) if m else None


_ITEM_NUMBER = re.compile(r"^[0-9]+(?:\.|)(?=\D)|^[（(][0-9]+[）)]")


def strip_item_number(text: str) -> str:
    """説明欄の項目に振られた通し番号を落とす。**宣言した団体でだけ呼ぶ。**

    ⚠️ **自動で判定しない。** 番号を振らない団体では、`1歳6か月児健診` のような
    数字で始まる正しい名前を削ってしまう。番号を振るかは実物を見ないと分からないので
    `sources.toml` の `numbered` が宣言する。

    落としてよいのは、番号が**目の中での並び順**しか表していないため
    （並びは `source_row` が保っている）。落とさないと `1議員報酬` のような名前になり、
    年度をまたぐと番号がずれて同じ事業が別の名前に見える。
    """
    return _ITEM_NUMBER.sub("", normalize(text), count=1)


def is_heading(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False
    # 欄外のノンブル（`－196－`）と、右頁の柱（`３款民生費`）。
    if re.fullmatch(r"[－\-—]+[0-9]+[－\-—]+", t):
        return True
    return t in HEADINGS
