-- **同じ親の下では、コードが名称を決めること。**
-- 破れているとコードと名称の対応が1対多になり、コード側で集計した結果と
-- 名称側で集計した結果が食い違う。
--
-- ⚠️ **`prefix2` の団体だけを見る。** `code-only` の団体（狛江市）は階層に名称の列が
-- 無く label が空なので、この検査は自明に通ってしまい意味を持たない。
-- そちら側の対応は label_column_determines_level.sql が別の形で見る。
-- 団体名を直書きせず `budget_code_style` から引くのは、3団体目の prefix2 が
-- 黙って検査されないまま通るのを防ぐため。
--
-- ⚠️ **階層を目までに絞っているのは重複ではなく宣言である。**
-- 三鷹市の細々節は同じ節の下でコードを再利用する（実測 710 箇所・1,615 行）ので、
-- 節以下にこの検査は成立しない。dbt_project.yml の `budget_levels`（全階層）へ
-- 寄せると検査の意味が変わる（実際に寄せて 710 件で落ちた）。
{% set levels = ['fund', 'kan', 'kou', 'moku'] %}
{% set checks = [] %}
{% for code, direction in budget_units() %}
  {% if var('budget_code_style')[code] == 'prefix2' %}
    {% for i in range(levels | length) %}
      {% do checks.append((code, direction, levels[i], levels[:i])) %}
    {% endfor %}
  {% endif %}
{% endfor %}

{% for code, direction, lv, ancestors in checks %}
{%- set parent = [] -%}
{%- for p in ancestors %}{% do parent.append(p ~ '_source') %}{% endfor -%}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ lv }}' as level,
       {% if parent %}{{ parent | join(" || chr(31) || ") }}{% else %}''{% endif %} as parent,
       {{ lv }}_code as code, count(distinct {{ lv }}_label) as 名称の異なり数
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
group by 1, 2, 3, 4, 5 having count(distinct {{ lv }}_label) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
