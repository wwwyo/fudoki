-- **セルからコードと名称を取り出した結果が、原典の書式どおりであること。**
--
-- 書式は団体ごとに違うので `budget_code_style` の宣言で分岐する。
--
--   prefix2（三鷹市）
--     コードと名称を繋ぐと原文セルに戻り、コードが2桁の数字であること。
--     ⚠️ **可逆なだけでは足りない。** `code = ''` / `label = source全体` でも繋げば戻るので、
--     先頭が2桁の数字でないセルは黙ってこの形になる（regexp_extract が空を返す）。
--
--   code-only（狛江市・多摩市）
--     セルそのものがコードで、コードが数字であること。
--     ⚠️ **原典がコードを持たない階層はここでは見ない**（`budget_levels_without_code`）。
--     多摩市の会計は名称しか無く、コードを要求すると名称を数字だと言わせることになる。
--     その階層に残っている保証は「名称が原文セルと一致すること」で、下の別の分岐が見る。
--     ⚠️ **名称は別列から来るので、繋いでも原文には戻らない。**
--     ここで見るのは「コードを原文セルからそのまま持ってきているか」と
--     「原典の書式（数字）が実際に成立しているか」の2点。
--     名称の対応は label_column_determines_level.sql が別に見る。
--
-- ⚠️ **`<>` ではなく `is distinct from`。** どちらかが NULL だと比較結果も NULL になり、
-- WHERE に残らない。NULL に壊れた行が不一致として報告されなくなる。
{% set checks = [] %}
{% for code, direction in budget_units() %}
  {% set no_code = var('budget_levels_without_code', {}).get(code, {}).get(direction, []) %}
  {% for lv in var('budget_levels')[code][direction] %}
    {% do checks.append((code, direction, lv, lv in no_code)) %}
  {% endfor %}
{% endfor %}

{% for code, direction, lv, without_code in checks %}
{%- set style = var('budget_code_style')[code] -%}
{#- その階層を持たない行のプレースホルダは検査から外す（コードではないため）。団体ごとに決まる。
    ⚠️ **宣言が空の団体で `not in ()` を書かない** — 空リストは構文エラーになる。
    プレースホルダを1つも使わない団体（多摩市）が実在する。 -#}
{%- set absent = var('budget_absent_level_markers')[code] | map('string') | map('replace', "'", "''") | list -%}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ lv }}' as level,
       source_row, {{ lv }}_source as source
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
where true
{%- if absent %}
  and {{ lv }}_source not in ({% for m in absent %}'{{ m }}'{% if not loop.last %}, {% endif %}{% endfor %})
{%- endif %}
{%- if without_code %}
  -- 原典がコードを持たない階層。code は空で、名称が原文セルそのものであることを見る
  and ({{ lv }}_code is distinct from ''
       or {{ lv }}_label is distinct from {{ lv }}_source)
{%- elif style == 'prefix2' %}
  and (({{ lv }}_code || {{ lv }}_label) is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d{2}'))
{%- else %}
  and ({{ lv }}_code is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d+'))
{%- endif %}
{% if not loop.last %}union all{% endif %}
{% endfor %}
