{{ config(severity = 'error') }}
-- **事業名がどこまで届いているかを毎回測り、下限を割ったら止める。**
--
-- ⚠️ カバレッジは主張ではなく検査にする。抽出器を直したときに悪化したら気づけないと、
-- 「名前が付く事業と付かない事業の境界に理由がない」状態のまま配ることになる。
--
-- 分母は**金額が 0 でない大事業**。0 の事業は同じ目に何件も並んで金額で区別できず、
-- 原理的に対応づけられない（実測で年度あたり 15〜36 件）。
-- 分母に入れると「原理的に無理なもの」で率が下がり、閾値が意味を持たなくなる。
--
-- 下限は 95%。実測は 2020〜2023 で 98.4〜99.4% なので、数ポイントの余裕を見た値。
{% set floor_pct = 95 %}
{#-
  ⚠️ **期待する年度を宣言する。** 分母を「事業名を抽出できた年度」から作ると、
  抽出が丸ごと失敗して0件になったとき**対象年度が消えて検査が空振りで通る**。
  「差が無いこと」を見る検査は両側が空なら成立してしまう、をここでも踏まないため。
-#}
{% set expected_years = [2020, 2021, 2022, 2023] %}

with expected as (
    {% for y in expected_years %}
    select {{ y }} as fiscal_year{% if not loop.last %} union all{% endif %}
    {% endfor %}
),

target as (
    select fiscal_year, fund_code, kan_code, kou_code, moku_code, daijigyo_code
    from {{ ref('stg_132195__expenditure') }}
    where fund_code = '1' and fiscal_year in (select fiscal_year from expected)
    group by all
    having sum(source_amount_executed) <> 0
),

named as (
    select fiscal_year, fund_code, kan_code, kou_code, moku_code, daijigyo_code
    from {{ ref('core_budget_project_names') }}
),

per_year as (
    select
        e.fiscal_year,
        count(t.daijigyo_code) as target_projects,
        count(n.daijigyo_code) as named_projects,
        case when count(t.daijigyo_code) = 0 then 0
             else round(100.0 * count(n.daijigyo_code) / count(t.daijigyo_code), 1) end as coverage_pct
    -- **宣言した年度を左に置く。** 対象が1件も無い年度も行として残り、0% として落ちる。
    from expected as e
    left join target as t using (fiscal_year)
    left join named as n
        using (fiscal_year, fund_code, kan_code, kou_code, moku_code, daijigyo_code)
    group by 1
)

select * from per_year where coverage_pct < {{ floor_pct }}

union all

-- ⚠️ **対象が痩せていないか。** 年度の宣言だけでは、原典の取り込みが縮んだときに
-- 分母ごと小さくなって率が保たれる。実測はどの年度も 486〜504 件なので、
-- 半分を切ったら取り込みか宣言が壊れた合図として止める。
select fiscal_year, target_projects, named_projects, coverage_pct
from per_year where target_projects < 240
