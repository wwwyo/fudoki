-- **コードと名称を繋ぐと原文セルに戻ること。**
-- 戻るからこそ配布物から *_source 列を落とせる。落としたあとで戻らなくなると、
-- 原典との対応が辿れない正本を配ることになる。
{% set exp = ['fund','kan','kou','moku','jikou','setsu','saisaisetsu'] %}
{% set rev = ['fund','kan','kou','moku','setsu','saisetsu','saisaisetsu'] %}
{% for lv in exp %}
select 'expenditure' as direction, '{{ lv }}' as level, source_row, {{ lv }}_source as source
from {{ ref('stg_132047__expenditure') }} where {{ lv }}_code || {{ lv }}_label <> {{ lv }}_source
union all
{% endfor %}
{% for lv in rev %}
select 'revenue', '{{ lv }}', source_row, {{ lv }}_source
from {{ ref('stg_132047__revenue') }} where {{ lv }}_code || {{ lv }}_label <> {{ lv }}_source
{% if not loop.last %}union all{% endif %}
{% endfor %}
