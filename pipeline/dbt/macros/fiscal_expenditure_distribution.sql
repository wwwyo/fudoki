{% macro fiscal_expenditure_distribution(code, kind) %}
{# 原典の節を経済分類として配らず、科目・事業の経路は内部モデルに残す。 #}
{%- set removed = ['phase_id', 'value', 'source_amount'] -%}
{%- if fiscal_amount_unit_is_column(code, 'expenditure') -%}
    {% do removed.append('source_amount_unit') %}
{%- endif -%}
{%- for level in var('fiscal_levels')[code]['expenditure'] if level in ['setsu', 'saisetsu', 'saisaisetsu'] -%}
    {% do removed.extend([level ~ '_code', level ~ '_label']) %}
{%- endfor -%}
{%- set budget = kind == 'initial_expenditure_budget' -%}
select p.* exclude({{ removed | join(', ') }}), p.value as amount,
    l.cofog_code, l.cofog_status, l.cofog_basis, l.consolidation, l.counterpart_fund
from {{ ref('pkg_' ~ code ~ '__expenditure') }} p
join {{ ref('api_fiscal_' ~ ('initial_expenditure_budget_lines' if budget else 'settlement_expenditure_lines')) }} l
    using (fiscal_line_id, dataset_id)
join {{ ref('int_fiscal_datasets') }} d using (dataset_id)
where d.document_kind = '{{ 'budget' if budget else 'settlement' }}'
    and p.phase_id = '{{ 'approved' if budget else 'executed' }}'
{% endmacro %}
