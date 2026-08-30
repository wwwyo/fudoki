-- **歳出と歳入の交差検算（年度・会計ごと）。**
--
-- ⚠️ **一般の不変条件ではない。取得元ごとに実測してから有効にする。**
-- 成立を確かめた団体と、許す差（丸め）だけを `budget_expenditure_revenue_balance` が宣言する。
-- **倍率はここでは宣言しない** — `budget_amounts` の primary が既に持っており、
-- 二重に持つと単位を直したときに検算だけ古い倍率で掛け続けて通ってしまう。
--
--   三鷹市 132047  令和6年度当初予算。同一の会計・年度・予算段階・収録範囲で完全一致（差 0）
--   狛江市 132195  2018〜2023 決算。歳出の予算計と歳入の予算現額が年度・会計別に一致する。
--                  ただし**歳入の予算現額は千円単位**なので円未満が丸められる。
--                  実測で差が出たのは 2021 一般会計（-585円）と 2023 一般会計（-105円）の2件で、
--                  どちらも 1,000 円未満。だから許容差を 1,000 円未満としてある。
--                  執行済額はここで比べない（歳出の執行と歳入の収入は釣り合う性質のものではない）。
--
-- ⚠️ **年度ごとに比べる。** 全年度を合計してから比べると、ある年度の過大と
-- 別の年度の過小が打ち消し合って通ってしまう。
{% set spec = var('budget_expenditure_revenue_balance') %}
{% set units = [] %}
{% for code, direction in budget_units() %}
  {% if code in spec %}
    {#- ⚠️ **倍率は年度で割れうる**（多摩市は令和3〜6年度が千円、令和7年度が円）。
        1つ選んで全年度に掛けると、片方の年度が 1000 倍ずれたまま比べることになる。 -#}
    {% set primary = var('budget_amounts')[code][direction] | selectattr('primary') | list %}
    {% do units.append((code, direction, primary[0]['name'])) %}
  {% endif %}
{% endfor %}

with sums as (
    {% for code, direction, name in units %}
    select '{{ code }}' as jurisdiction, fiscal_year, fund_label,
           '{{ direction }}' as direction,
           sum({{ budget_amount_value_sql(code, direction, name) }}) as amount
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }} group by 1, 2, 3, 4
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

paired as (
    select
        jurisdiction, fiscal_year, fund_label,
        sum(amount) filter (where direction = 'expenditure') as 歳出,
        sum(amount) filter (where direction = 'revenue')     as 歳入
    from sums group by 1, 2, 3
)

select *, 歳出 - 歳入 as 差
from paired
where 歳出 is null or 歳入 is null
   or abs(歳出 - 歳入) >= case jurisdiction
      {% for code in spec.keys() %}when '{{ code }}' then {{ spec[code]['tolerance_yen'] }} {% endfor %}
   end
