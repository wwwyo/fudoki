{{ config(materialized = 'external', location = '../data/budget/datapackages/131016/revenue.csv', format = 'csv') }}
-- 正本（歳入）。**団体ごと・全年度で1リソース。**
--
-- (団体, 年度) ごとに分けると全量で 558 パッケージになり、
-- 「年をまたぐ比較ができない」という出発点を成果物の形で再現してしまう。
-- 年度は fiscal_year 列で区別する。
--
-- 落とした列と、その理由。
--   *_source は code と label から復元できる（コードを持たない階層は label が原文セルそのもの）。
--   原典そのものは data/budget/raw/ に Parquet で入っているので join できる。
--   団体・phase・通貨・direction  全行同じ値。datapackage.json のメタデータに属する
--
-- ⚠️ **他の団体と列を揃えない。** 千代田区の歳入の説明欄は1段しかない（事業だけ）。
-- 昭島市の歳入は節の内訳が説明欄に来るので、同じ様式でも団体で作りが違う。
-- 揃えることが「同じ概念だ」という判断になるので、正本は団体ごとの形のまま出す。
{% set amounts = var('budget_amounts')['131016']['revenue'] %}
{#- ⚠️ **宣言の件数で見る。** 止めたいのは段階が増えた場合（行の展開が要る）と、
    年度で宣言が割れた場合（列名・単位・倍率を年度で選ぶ形が要る）の両方で、
    このモデルはどちらにも対応していない。 -#}
{% if amounts | length != 1 %}
  {{ exceptions.raise_compiler_error(
      '131016/revenue: 金額の宣言が ' ~ amounts | length ~ ' 件ある。'
      ~ 'このモデルは単一段階・全年度共通の宣言を前提にしている。'
      ~ '段階が増えたなら段階ごとの行へ展開する形へ、年度で割れたなら'
      ~ 'budget_amount_value_sql のように年度で選ぶ形へ変えること') }}
{% endif %}
{% set amount = amounts[0] %}
select
    budget_line_id,
    fiscal_year,
    phase_id,
    source_row,
    fund_code,
    fund_label,
    kan_code,
    kan_label,
    kou_code,
    kou_label,
    moku_code,
    moku_label,
    jigyo_code,
    jigyo_label,
    -- 円へ正規化した値と、原典の値を別に残す。
    -- FDP には倍率を表す ColumnType が無いため、両方置く。
    -- 単位（千円）は全行同じなので datapackage.json のメタデータへ。
    -- ⚠️ **倍率を直書きしない。** `budget_amounts` が宣言しており、
    -- descriptor もそこから作る。写すと単位を直したとき片方だけ変わる。
    source_amount * {{ amount['multiplier'] }} as value,
    source_amount
from {{ ref('stg_131016__revenue') }}
-- 年度をまたぐと source_row だけでは並びが決まらない
order by fiscal_year, source_row
