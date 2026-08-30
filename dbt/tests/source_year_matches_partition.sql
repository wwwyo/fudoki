-- **原典に年度の列がある団体で、その値が partition の年度と一致すること。**
--
-- 年度は取得側が CKAN のリソース名から解決して partition に焼いている。
-- ⚠️ 三鷹市には年度の列が無く、リソース名だけが唯一の出所だった（和暦の表記も揺れていた）。
-- 狛江市は原典に「年度」の列を持っているので、**別の経路で照合できる。**
-- 一致しなければ、リソース名から年度を取り違えたか、自治体が中身を差し替えている。
--
-- 列名も**表記**も団体ごとに違うので、宣言（`budget_source_year_columns`）から引く。
-- 宣言の無い団体（年度の列を持たない団体）はここでは検査できない。
--
-- ⚠️ **表記の違いを「照合できない」で済ませない。** 多摩市の年度は `R4` という
-- 和暦の略記で、西暦の partition と直接は比べられない。宣言をやめれば検査は通るが、
-- 原典が持っている年度を誰も見ていない状態になるので、partition 側を表記へ寄せて比べる。
{% set units = [] %}
{% for code, direction in budget_units() %}
  {% if code in var('budget_source_year_columns') %}
    {% do units.append((code, direction, var('budget_source_year_columns')[code])) %}
  {% endif %}
{% endfor %}

{% for code, direction, spec in units %}
{#- partition の西暦を原典の表記へ直す。令和元年 = 2019 年度 -#}
{%- if spec['notation'] == 'western' -%}
  {%- set expected = "cast(year as varchar)" -%}
{%- elif spec['notation'] == 'reiwa-abbrev' -%}
  {%- set expected = western_to_reiwa_abbrev('year') -%}
{%- else -%}
  {{ exceptions.raise_compiler_error(
      code ~ ': budget_source_year_columns の notation「' ~ spec['notation'] ~ '」は未定義') }}
{%- endif -%}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction,
       year as partition_year, "{{ spec['column'] }}" as source_year, count(*) as rows
from {{ source('raw_' ~ code, direction) }}
where cast("{{ spec['column'] }}" as varchar) is distinct from {{ expected }}
group by 1, 2, 3, 4
{% if not loop.last %}union all{% endif %}
{% endfor %}
