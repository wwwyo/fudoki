-- **セルからコードと名称を取り出した結果が、原典の書式どおりであること。**
--
-- 書式は団体ごとに違うので `budget_code_style` の宣言で分岐する。
--
--   prefix2（三鷹市）
--     コードと名称を繋ぐと原文セルに戻り、コードが2桁の数字であること。
--     ⚠️ **可逆なだけでは足りない。** `code = ''` / `label = source全体` でも繋げば戻るので、
--     先頭が2桁の数字でないセルは黙ってこの形になる（regexp_extract が空を返す）。
--
--   code-only（狛江市）
--     セルそのものがコードで、コードが数字であること。
--     ⚠️ **名称は別列から来るので、繋いでも原文には戻らない。**
--     ここで見るのは「コードを原文セルからそのまま持ってきているか」と
--     「原典の書式（数字）が実際に成立しているか」の2点。
--     名称の対応は label_column_determines_level.sql が別に見る。
--
-- ⚠️ **`<>` ではなく `is distinct from`。** どちらかが NULL だと比較結果も NULL になり、
-- WHERE に残らない。NULL に壊れた行が不一致として報告されなくなる。
{% set codes = var('budget_levels').keys() | list | sort %}
{% set blocks = [] %}
{% for code in codes %}{% for direction in var('budget_levels')[code].keys() %}
  {% do blocks.append((code, direction)) %}
{% endfor %}{% endfor %}

{% for code, direction in blocks %}
{%- set style = var('budget_code_style')[code] -%}
{#- その階層を持たない行のプレースホルダは検査から外す（コードではないため） -#}
{%- set absent = var('budget_absent_level_markers')[code] | map('string') | map('replace', "'", "''") | list -%}
{% for lv in var('budget_levels')[code][direction] %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ lv }}' as level,
       source_row, {{ lv }}_source as source
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
where {{ lv }}_source not in ({% for m in absent %}'{{ m }}'{% if not loop.last %},{% endif %}{% endfor %})
{%- if style == 'prefix2' %}
  and (({{ lv }}_code || {{ lv }}_label) is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d{2}'))
{%- else %}
  and ({{ lv }}_code is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d+'))
{%- endif %}
union all
{% endfor %}
{% endfor %}
select null, null, null, null, null where false
