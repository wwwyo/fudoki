{{ config(materialized = 'external', location = '../data/budget/datapackages/132241/expenditure.csv', format = 'csv') }}
-- 正本（歳出）。**団体ごと・全年度で1リソース。**
--
-- 落とした列と、その理由。
--   *_source        code と label から復元できる（会計だけは code が空で label が原文セル）。
--                   原典そのものは data/budget/raw/ に Parquet で入っているので join できる
--   団体・phase・通貨・direction  全行同じ値。datapackage.json のメタデータに属する
--
-- ⚠️ **三鷹市・狛江市と列を揃えない。** 多摩市の事業階層は目の下の「細目」で、名称を持つ（例: `子ども若者育成支援事業`）。
-- 揃えることが「同じ概念だ」という判断になるので、正本は団体ごとの形のまま出す。
{% set amounts = var('budget_amounts')['132241']['expenditure'] %}
{% if amounts | length != 1 %}
  {{ exceptions.raise_compiler_error(
      '132241/expenditure: 予算段階が ' ~ amounts | length ~ ' 種類ある。'
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
    saimoku_code,
    saimoku_label,
    setsu_code,
    setsu_label,
    -- 円へ正規化した値と、原典の値を別に残す。
    -- FDP には倍率を表す ColumnType が無いため、両方置く。
    -- ⚠️ 単位（千円）は原典の列名が名乗っていない。根拠は budget_amounts の宣言にある。
    source_amount * {{ amount['multiplier'] }} as value,
    source_amount
from {{ ref('stg_132241__expenditure') }}
-- 年度をまたぐと source_row だけでは並びが決まらない
order by fiscal_year, source_row
