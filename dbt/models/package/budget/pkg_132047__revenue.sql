{{ config(materialized = 'external', location = '../data/budget/packages/132047/revenue.csv', format = 'csv') }}
-- 正本（歳入）。**団体ごと・全年度で1リソース。**
--
-- (団体, 年度) ごとに分けると全量で 558 パッケージになり、
-- 「年をまたぐ比較ができない」という出発点を成果物の形で再現してしまう。
-- 年度は fiscal_year 列で区別する。
--
-- 落とした列と、その理由。
--   *_source        code と label から復元できる（不一致0件を実測）。
--                   原典そのものは data/budget/raw/ に Parquet で入っているので join できる
--   hierarchy_path  コード列から導出できる
--   団体・phase・通貨・direction  全行同じ値。datapackage.json のメタデータに属する
{% set amounts = var('budget_amounts')['132047']['revenue'] %}
{% if amounts | length != 1 %}
  {{ exceptions.raise_compiler_error(
      '132047/revenue: 予算段階が ' ~ amounts | length ~ ' 種類ある。'
      ~ 'このモデルは単一段階を前提にしているので、段階ごとの行へ展開する形へ変えること') }}
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
    setsu_code,
    setsu_label,
    saisetsu_code,
    saisetsu_label,
    saisaisetsu_code,
    saisaisetsu_label,
    -- 円へ正規化した値と、原典の値を別に残す。
    -- FDP には倍率を表す ColumnType が無いため、両方置く。
    -- 単位（千円）は全行同じなので datapackage.json のメタデータへ。
    -- ⚠️ **倍率を直書きしない。** `budget_amounts` が宣言しており、
    -- descriptor もそこから作る。写すと単位を直したとき片方だけ変わる。
    source_amount * {{ amount['multiplier'] }} as value,
    source_amount
from {{ ref('stg_132047__revenue') }}
-- 年度をまたぐと source_row だけでは並びが決まらない
order by fiscal_year, source_row
