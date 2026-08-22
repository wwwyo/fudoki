-- **FDP の複合主キーが一意であること。**
-- budget_line_id はハッシュなので、衝突していないことを別の経路でも確かめる。
-- 階層のコードと名称を全部並べたものが一意なら、識別子の導出が壊れていても検出できる。
--
-- 階層の定義は dbt_project.yml の `budget_levels` が正本（団体ごとに違う）。
-- ⚠️ **階層だけでは一意にならない団体がある。** 狛江市は所属と予算区分まで含めて
-- 初めて一意になる（実測 2023 歳出で階層だけだと 2,224 行が 1,855 通りに潰れる）。
-- 追加の同一性の列は `budget_extra_key_columns` が宣言し、識別子の材料でもある。
{% set jurisdictions = var('budget_levels') %}
{% set blocks = [] %}
{% for code, dirs in jurisdictions.items() %}
  {% for direction, levels in dirs.items() %}
    {% do blocks.append((code, direction, levels)) %}
  {% endfor %}
{% endfor %}

{% for code, direction, levels in blocks %}
{% set parts = [] %}
{% for lv in levels %}{% do parts.append(lv ~ '_code') %}{% do parts.append(lv ~ '_label') %}{% endfor %}
{% for k in var('budget_extra_key_columns')[code][direction] %}
  {% do parts.append(k ~ '_code') %}{% do parts.append(k ~ '_label') %}
{% endfor %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, key, n
from (
    select
        -- ⚠️ **年度・予算段階・direction をキーに含める。**
        -- 含めないと、同じ科目階層が翌年度にも現れた時点で重複として落ちる
        -- （正本は団体ごと全年度を1リソースに入れる方針なので必ず起きる）。
        -- 区切りは U+001F（原典に現れない制御文字）。連結だけだと
        -- 隣り合う列の境目がずれた重複を取り逃がす。
        fiscal_year || chr(31) || phase_id || chr(31) || direction || chr(31)
        || {{ parts | join(" || chr(31) || ") }} as key,
        count(*) as n
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    group by 1
    having count(*) > 1
)
{% if not loop.last %}union all{% endif %}
{% endfor %}
