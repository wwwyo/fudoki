{{ config(materialized = 'external', location = '../data/budget/packages/132195/revenue.csv', format = 'csv') }}
-- 狛江市 正本（歳入）。**団体ごと・全年度で1リソース。**
--
-- ⚠️ **1行が原典の1行ではない。原典1行 × 予算段階の数だけ行がある。**
-- 原典は決算書なので、1行に予算現額と収入累計の2つの金額を持つ。
-- FDP は `value` の列型を1つしか持たず、予算段階は `phase:id` という**行の列**で表す。
-- だから金額の列を3本並べるのではなく、段階ごとの行へ展開する。
-- 段階の宣言は dbt_project.yml の `budget_amounts` にある。
-- 主キーは (budget_line_id, phase_id)。budget_line_id だけでは一意でない。
--
-- ⚠️ **予算現額だけ単位が千円で、収入累計は円。** 同じリソース内で単位が割れるので、
-- 単位を行の列（source_amount_unit）に持つ。円へ直した値は value にある。
-- 歳入の予算現額（千円）は歳出の予算計と会計別に一致する（円未満の丸めを除く。実測6年度）。
--
-- ⚠️ **款・項・目・節の `_label` は空。** 原典に名称の列が無いためで、
-- 取り込みで落としたのではない。名称を持つのは会計と細節（科目名称）だけ。
--
-- 落とした列と、その理由。
--   *_source                 code と label から復元できない団体もあるが、狛江市は code = 原文セル
--   予算残額 / 予算比 / 収入率  予算現額と収入累計から導出できる
--   調定累計 / 不納欠損額 / 還付未済額 / 収入未済額
--                            収入の内訳（調定 − 収入 − 不納欠損 − 収入未済 = 0）であって
--                            予算段階の金額ではない。段階の列へ混ぜると二重に数える
--   対象年月                  リソース全体で1つの値（証跡は data/budget/raw/ の provenance.json）
with lines as (
    select * from {{ ref('stg_132195__revenue') }}
)

{% set amounts = var('budget_amounts')['132195']['revenue'] %}
{% for a in amounts %}
select
    budget_line_id,
    fiscal_year,
    '{{ a["phase"] }}' as phase_id,
    '{{ a["phase_label"] }}' as phase_label,
    source_row,
    -- 所属（部課）。**階層だけでは行が一意にならない**ので識別子の材料でもある。
    -- ⚠️ 歳入には所属名称の列が原典に無いので label は空。
    org_code,
    org_label,
    -- 予算区分（現年度 / 繰越明許 / 事故繰越）。同じ科目に複数の区分が並ぶ。
    budget_class_code,
    budget_class_label,
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
    -- 円へ正規化した値と、原典の値・単位を別に残す。
    -- FDP には倍率を表す ColumnType が無いため、両方置く。
    -- ⚠️ 単位は**行ごとに違う**（予算現額は千円、収入累計は円）。
    -- 三鷹市のように datapackage.json の定数へ出すことはできない。
    {{ a['name'] }} * {{ a['multiplier'] }} as value,
    {{ a['name'] }} as source_amount,
    '{{ a["unit"] }}' as source_amount_unit
from lines
{% if not loop.last %}union all{% endif %}
{% endfor %}
-- 年度をまたぐと source_row だけでは並びが決まらない。段階も並びに含める。
order by fiscal_year, source_row, phase_id
