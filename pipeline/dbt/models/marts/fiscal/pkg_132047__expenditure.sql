{{ config(materialized = 'external', location = env_var('FUDOKI_INTERNAL_PACKAGE_DIR') ~ '/132047/expenditure.csv', format = 'csv') }}
-- 正本（歳出）。**団体ごと・全年度で1リソース。**
--
-- (団体, 年度) ごとに分けると全量で 558 パッケージになり、
-- 「年をまたぐ比較ができない」という出発点を成果物の形で再現してしまう。
-- 年度は fiscal_year 列で区別する。
--
-- 落とした列と、その理由。
--   *_source        code と label から復元できる（不一致0件を実測）。
--                   原典そのものは pipeline/.cache/ 配下の raw/ に Parquet で入っているので join できる
--   hierarchy_path  コード列から導出できる
--   団体・phase・通貨・direction  全行同じ値。datapackage.json のメタデータに属する
select
    fiscal_line_id,
    dataset_id,
    document_kind,
    origin_sha256,
    fiscal_year,
    {{ fiscal_amount_attr_sql('132047', 'expenditure', 'source_amount', 'phase', true) }} as phase_id,
    source_row,
    fund_code,
    fund_label,
    kan_code,
    kan_label,
    kou_code,
    kou_label,
    moku_code,
    moku_label,
    jikou_code,
    jikou_label,
    setsu_code,
    setsu_label,
    saisaisetsu_code,
    saisaisetsu_label,
    -- 円へ正規化した値と、原典の値を別に残す。
    -- FDP には倍率を表す ColumnType が無いため、両方置く。
    -- 単位（千円）は全行同じなので datapackage.json のメタデータへ。
    -- ⚠️ **倍率を直書きしない。** `fiscal_amounts` が宣言しており、
    -- descriptor もそこから作る。写すと単位を直したとき片方だけ変わる。
    {{ fiscal_amount_value_sql('132047', 'expenditure', 'source_amount') }} as value,
    source_amount,
    {{ fiscal_amount_attr_sql('132047', 'expenditure', 'source_amount', 'unit', true) }} as source_amount_unit
from {{ ref('stg_132047__expenditure') }}
-- 年度をまたぐと source_row だけでは並びが決まらない
order by fiscal_year, document_kind, origin_sha256, source_row
