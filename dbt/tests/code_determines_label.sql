-- **同じ親の下では、コードが名称を決めること。**
-- 破れているとコードと名称の対応が1対多になり、コード側で集計した結果と
-- 名称側で集計した結果が食い違う。
--
-- ⚠️ **階層を目までに絞っているのは重複ではなく宣言である。**
-- 三鷹市の細々節は同じ節の下でコードを再利用する（実測 710 箇所・1,615 行）ので、
-- 節以下にこの検査は成立しない。dbt_project.yml の `budget_levels`（全階層）へ
-- 寄せると検査の意味が変わる（実際に寄せて 710 件で落ちた）。
{% set levels = [
  ('expenditure', 'fund', ''), ('expenditure', 'kan', 'fund_source'),
  ('expenditure', 'kou', 'fund_source || kan_source'), ('expenditure', 'moku', 'fund_source || kan_source || kou_source'),
  ('revenue', 'fund', ''), ('revenue', 'kan', 'fund_source'),
  ('revenue', 'kou', 'fund_source || kan_source'), ('revenue', 'moku', 'fund_source || kan_source || kou_source'),
] %}
{% for direction, lv, parent in levels %}
select '{{ direction }}' as direction, '{{ lv }}' as level,
       {% if parent %}{{ parent }}{% else %}''{% endif %} as parent,
       {{ lv }}_code as code, count(distinct {{ lv }}_label) as 名称の異なり数
from {{ ref('stg_132047__' ~ direction) }}
group by 1, 2, 3, 4 having count(distinct {{ lv }}_label) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
