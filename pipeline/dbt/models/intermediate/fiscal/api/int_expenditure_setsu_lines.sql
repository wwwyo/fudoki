{#
  歳出予算の原典行へ、事業×節の集約キーと下位経路を付ける。**集約の規則はここが正本。**

  - `group_path_key`: dataset の中で「款・項・目・事業の順序付き経路 + 追加区分」を
    識別する。節より上の原典セルをそのまま連結する（コードではなくセル全文。
    識別子の材料は fiscal_staging と同じ原則）。
  - `sub_path_json`: 節より下の順序付き下位経路（細節・細々節等）。
    自治体が空欄・プレースホルダで埋めた段は除く。節直下の行は空の下位経路。
  - `expenditure_setsu_id`: 原典の節名称と `expenditure_setsu_map` の宣言で対応づけた
    法定区分。節を持たない団体（千代田区）や節が空欄の行は NULL。
  - `line_granularity`: 同じ経路・追加区分・節の末端行が分類（COFOG・連結判断）を
    共有する場合だけ `expenditure_setsu`。それ以外は `origin_line`。
    NULL の節をまとめて集約しない。
#}
{%- set codes = [] -%}
{%- for c, d in fiscal_units() if d == 'expenditure' %}{% do codes.append(c) %}{% endfor -%}
{% for code in codes %}
{%- set levels = var('fiscal_levels')[code]['expenditure'] -%}
{%- set dims = var('fiscal_extra_key_columns')[code]['expenditure'] -%}
{%- set absent = var('fiscal_absent_level_markers').get(code, []) -%}
{%- set absent_list = absent | map('replace', "'", "''") | join("', '") -%}
{%- set sidx = levels.index('setsu') if 'setsu' in levels else -1 -%}
{%- set setsu_present = "s.setsu_source is not null and s.setsu_source != ''" ~ (" and s.setsu_source not in ('" ~ absent_list ~ "')" if absent else "") -%}
select
    s.fiscal_line_id, s.dataset_id, s.source_row, s.fund_code, s.fund_label,
    d.jurisdiction_code, d.fiscal_year,
    a.value as amount,
    l.cofog_code, l.cofog_status, l.cofog_basis, l.consolidation, l.counterpart_fund,
{%- if sidx >= 0 %}
    {%- set above = levels[:sidx] -%}
    {%- set below = levels[sidx + 1:] -%}
{%- set key_parts = [] -%}
    {%- for lv in above %}{% do key_parts.append('s.' ~ lv ~ '_source') %}{% endfor -%}
    {%- for dm in dims %}{% do key_parts.append('s.' ~ dm ~ '_source') %}{% endfor -%}
    {{ key_parts | join(" || chr(31) || ") }} as group_path_key,
    {{ sidx }} as setsu_ordinal,
    {{ setsu_present }} as setsu_present,
    case when {{ setsu_present }} then m.expenditure_setsu_id else null end as expenditure_setsu_id,
    case when {{ setsu_present }} then s.setsu_label else null end as setsu_label,
{%- if below %}
    '[' || coalesce(concat_ws(',',
      {%- for lv in below %}
        case when s.{{ lv }}_source is not null and s.{{ lv }}_source != ''
          {%- if absent %} and s.{{ lv }}_source not in ('{{ absent_list }}'){% endif %}
          then json_object('level', '{{ lv }}', 'code', coalesce(s.{{ lv }}_code, ''), 'label', coalesce(s.{{ lv }}_label, '')) end
        {%- if not loop.last %},{% endif %}
      {%- endfor %}), '') || ']' as sub_path_json,
{%- else %}
    '[]' as sub_path_json,
{%- endif %}
{%- else %}
    s.fiscal_line_id as group_path_key,
    {{ levels | length }} as setsu_ordinal,
    false as setsu_present,
    null::varchar as expenditure_setsu_id,
    null::varchar as setsu_label,
    '[]' as sub_path_json,
{%- endif %}
from {{ ref('stg_' ~ code ~ '__expenditure') }} as s
join {{ ref('int_fiscal_datasets') }} as d using (dataset_id)
join {{ ref('int_fiscal_lines') }} as l using (fiscal_line_id)
join {{ ref('int_fiscal_amounts') }} as a
  on a.fiscal_line_id = s.fiscal_line_id and a.phase = 'approved'
{%- if sidx >= 0 %}
left join {{ ref('expenditure_setsu_map') }} as m
  on m.jurisdiction_code = d.jurisdiction_code and m.setsu_label = s.setsu_label
{%- endif %}
where d.document_kind = 'budget'
{% if not loop.last %}union all
{% endif %}
{%- endfor %}
