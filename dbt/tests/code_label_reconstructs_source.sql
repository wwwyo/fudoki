-- **コードと名称を繋ぐと原文セルに戻り、コードが2桁の数字であること。**
--
-- ⚠️ **可逆なだけでは足りない。** `code = ''` / `label = source全体` でも繋げば戻るので、
-- 先頭が2桁の数字でないセルは黙ってこの形になる（regexp_extract が空を返す）。
-- 「先頭2桁がコード」という原典の書式が実際に成立していることを別に確かめる。
--
-- ⚠️ **`<>` ではなく `is distinct from`。** どちらかが NULL だと比較結果も NULL になり、
-- WHERE に残らない。NULL に壊れた行が不一致として報告されなくなる。
{% set exp = ['fund','kan','kou','moku','jikou','setsu','saisaisetsu'] %}
{% set rev = ['fund','kan','kou','moku','setsu','saisetsu','saisaisetsu'] %}
{# その階層を持たない行のプレースホルダは検査から外す（コードではないため） #}
{% set absent = var('budget_absent_level_markers')['132047'] %}
{% set absent_sql = absent | map('string') | map('replace', "'", "''") | list %}
{% for lv in exp %}
select 'expenditure' as direction, '{{ lv }}' as level, source_row, {{ lv }}_source as source
from {{ ref('stg_132047__expenditure') }}
where {{ lv }}_source not in ({% for m in absent_sql %}'{{ m }}'{% if not loop.last %},{% endif %}{% endfor %})
  and (({{ lv }}_code || {{ lv }}_label) is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d{2}'))
union all
{% endfor %}
{% for lv in rev %}
select 'revenue', '{{ lv }}', source_row, {{ lv }}_source
from {{ ref('stg_132047__revenue') }}
where {{ lv }}_source not in ({% for m in absent_sql %}'{{ m }}'{% if not loop.last %},{% endif %}{% endfor %})
  and (({{ lv }}_code || {{ lv }}_label) is distinct from {{ lv }}_source
       or not regexp_full_match({{ lv }}_code, '\d{2}'))
{% if not loop.last %}union all{% endif %}
{% endfor %}
