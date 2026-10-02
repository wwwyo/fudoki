"""# 予算資料の粒度プロファイル

自治体が公開する予算・決算の表が、どの粒度まで届いているかを**列構成から**判定する。
資料名では判定しない（パーサ設計の原則3）。

## 法定の語彙と自治体固有の語彙を分ける

款・項・目・節は地方自治法にもとづく区分で、どの自治体でも同じ語を使う。
一方、目の下に置く事業階層の呼び名は法定ではない。
三鷹市は「事項」、狛江市は「大事業 / 中事業 / 小事業」、多摩市は「細目」と、団体ごとに違う。

**この2つを1つの共有配列に混ぜてはいけない**（原則5「例外は一般化せず、その対象に閉じる」）。
混ぜると、次の団体で新しい呼び名に出会うたびに共有配列へ足すことになり、
その語が別団体の無関係な列（「事業者名」など）へ誤ヒットする危険が全団体へ波及する。

そこで事業階層の列名は**団体コードごとに宣言**し、未知の団体にだけ推定を当てる。
判定結果には `basis` を付けて、宣言によるものか推定によるものかを区別する。

⚠️ **推定の語彙に漏れがあると、事業単位に届く団体を取りこぼす。**
実際に「細目」が無かったため、多摩市が `account-item` と判定され、
事業単位に届く3団体目を1年近く見落としていた（2026-08-30 実測で判明）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 到達した粒度。「目より下の事業階層まで届いているか」だけが本質的な区別
GRANULARITIES = ("project", "account-item", "category", "indicator", "unchecked")

# 深いほど大きい。`unchecked` は順序比較の対象にしない
GRANULARITY_RANK = {"project": 4, "account-item": 3, "category": 2, "indicator": 1}

# 地方自治法にもとづく科目区分。全自治体で共通の語
STATUTORY_LEVELS = ("款", "項", "目", "節")

# 事業階層の列名。**団体コードごとに宣言する**。実測で確認した団体だけを書く（推測で足さない）
ACTIVITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "132047": ("事項",),                          # 三鷹市
    "132195": ("大事業", "中事業", "小事業"),      # 狛江市
    "132241": ("細目", "細目名称"),                # 多摩市（歳出。歳入は細節）
}

# 未宣言の団体に当てる推定用。確定ではないので判定に basis="inferred" を付ける
ACTIVITY_HINTS = ("事業", "事項", "施策", "細目", "細事業")
# 事業階層ではないのに上の推定に当たる列
NOT_ACTIVITY = ("事業者", "事業所", "事業年度", "事業別", "事業収入", "事業費")

CATEGORY_AXES = ("目的別", "性質別")
INDICATORS = ("比率", "指標", "財政力", "経常収支", "将来負担")
# 金額列。`額` の1文字を入れると他の語がすべてそれに吸収され、
# 「指摘金額」のような非予算データまで拾うので、具体的な語に限る
AMOUNTS = ("予算額", "決算額", "金額", "予算計", "予算現額", "執行累計", "支出済額", "収入済額")

# 表題に含まれれば予算資料の候補とみなす語。カタログが持つ無関係な資料を落とす
RELEVANT_TITLE_WORDS = ("予算", "決算", "歳出", "歳入", "財政", "款", "事業別")

# 列構成を測れる形式。⚠️ **CSV だけに絞らない** — 予算を XLSX / XLS でしか
# 出していない団体が実在し（練馬区・大田区・目黒区・調布市・町田市ほか）、
# CSV 限定だとその団体が丸ごと「予算データ無し」に見える（2026-08-30 実測）
READABLE_FORMATS = ("CSV", "XLSX", "XLSM", "XLS")


@dataclass(frozen=True)
class GranularityResult:
    granularity: str
    # 判定の根拠。宣言済みの団体か、未知の団体への推定か
    basis: str
    hits: tuple[str, ...]


def detect_direction(title: str) -> str:
    """歳出か歳入か。歳出の粒度を測るのが目的なので、歳入を歳出の代表にしない。

    ⚠️ 歳入と歳出は資料名かリソース名にしか書かれていない。
    """
    revenue = "歳入" in title or "収入" in title
    expenditure = "歳出" in title or "支出" in title
    if expenditure and not revenue:
        return "expenditure"
    if revenue and not expenditure:
        return "revenue"
    return "unknown"


def normalize_column(c: object) -> str:
    """列名の連番プレフィックスと単位の括弧を外す（三鷹は `04目`、狛江は `予算額(円)`）"""
    s = re.sub(r"^[0-9０-９]+[._\-\s]*", "", str(c or "").strip())
    s = re.sub(r"[（(\[].*?[）)\]]", "", s)
    return s.strip()


def _activity_columns(cols: list[str], jurisdiction_code: str) -> tuple[list[str], str]:
    declared = ACTIVITY_COLUMNS.get(jurisdiction_code)
    if declared is not None:
        return [c for c in cols if c in declared], "declared"
    hit = [c for c in cols
           if any(k in c for k in ACTIVITY_HINTS) and not any(n in c for n in NOT_ACTIVITY)]
    return hit, "inferred"


def classify_granularity(header: list[str], jurisdiction_code: str) -> GranularityResult:
    """列構成から粒度を判定する。深い順に見て最初に当たったものを返す。"""
    cols = [c for c in (normalize_column(h) for h in header) if c]
    joined = "|".join(cols)
    has_amount = any(k in joined for k in AMOUNTS)
    levels = [k for k in STATUTORY_LEVELS if k in cols]
    reaches_moku = "目" in levels
    activity, basis = _activity_columns(cols, jurisdiction_code)

    if activity and reaches_moku and has_amount:
        return GranularityResult("project", basis, tuple(activity + levels))
    if reaches_moku and has_amount:
        return GranularityResult("account-item", basis, tuple(levels))
    if (levels or any(k in joined for k in CATEGORY_AXES)) and has_amount:
        return GranularityResult("category", basis, tuple(levels))
    indicators = [k for k in INDICATORS if k in joined]
    if indicators:
        return GranularityResult("indicator", basis, tuple(indicators))
    return GranularityResult("unchecked", basis, ())


def score_header_row(cells: list[str]) -> int:
    """その行が見出しらしいか。科目の語を多く含むほど高い。

    ⚠️ **見出しは1行目とは限らない。** 自治体の Excel は表題・所管課・単位の行が
    先に来ることが多く、1行目だけを見ると「所管課」を列名として判定してしまう。
    """
    levels = sum(1 for k in STATUTORY_LEVELS if k in cells)
    activity = sum(1 for c in cells
                   if any(k in c for k in ACTIVITY_HINTS) and not any(n in c for n in NOT_ACTIVITY))
    return levels * 2 + activity
