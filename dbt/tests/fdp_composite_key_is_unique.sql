-- **FDP の複合主キーが一意であること。**
-- budget_line_id はハッシュなので、衝突していないことを別の経路でも確かめる。
-- 階層のコードと名称を全部並べたものが一意なら、識別子の導出が壊れていても検出できる。
--
-- 階層の定義は dbt_project.yml の `budget_levels` が正本（団体ごとに違う）。
{% set jurisdictions = var('budget_levels') %}
{% set blocks = [] %}
{% for code, dirs in jurisdictions.items() %}
  {% for direction, levels in dirs.items() %}
    {% do blocks.append((code, direction, levels)) %}
  {% endfor %}
{% endfor %}

{% for code, direction, levels in blocks %}
{% set codes = [] %}{% set labels = [] %}
{% for lv in levels %}{% do codes.append(lv ~ '_code') %}{% do labels.append(lv ~ '_label') %}{% endfor %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, key, n
from (
    select
        -- ⚠️ **年度・予算段階・direction をキーに含める。**
        -- 含めないと、同じ科目階層が翌年度にも現れた時点で重複として落ちる
        -- （正本は団体ごと全年度を1リソースに入れる方針なので必ず起きる）。
        fiscal_year || '/' || phase_id || '/' || direction || '/'
        || {{ codes | join(" || '/' || ") }}
        || '|' || {{ labels | join(' || ') }} as key,
        count(*) as n
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    group by 1
    having count(*) > 1
)
{% if not loop.last %}union all{% endif %}
{% endfor %}
