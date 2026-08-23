-- **原典に年度の列がある団体で、その値が partition の年度と一致すること。**
--
-- 年度は取得側が CKAN のリソース名から解決して partition に焼いている。
-- ⚠️ 三鷹市には年度の列が無く、リソース名だけが唯一の出所だった（和暦の表記も揺れていた）。
-- 狛江市は原典に「年度」の列を持っているので、**別の経路で照合できる。**
-- 一致しなければ、リソース名から年度を取り違えたか、自治体が中身を差し替えている。
--
-- 列名は団体ごとに違いうるので宣言（`budget_source_year_columns`）から引く。
-- 宣言の無い団体（年度の列を持たない団体）はここでは検査できない。
{% set units = [] %}
{% for code, direction in budget_units() %}
  {% if code in var('budget_source_year_columns') %}
    {% do units.append((code, direction, var('budget_source_year_columns')[code])) %}
  {% endif %}
{% endfor %}

{% for code, direction, column in units %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction,
       year as partition_year, "{{ column }}" as source_year, count(*) as rows
from {{ source('raw_' ~ code, direction) }}
where cast("{{ column }}" as varchar) is distinct from cast(year as varchar)
group by 1, 2, 3, 4
{% if not loop.last %}union all{% endif %}
{% endfor %}
