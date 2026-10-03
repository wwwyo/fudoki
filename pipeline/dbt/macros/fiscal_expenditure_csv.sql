{% macro fiscal_expenditure_csv(code, kind) %}
{# 決算は原典の節を経済分類として配らず、科目・事業の経路は内部モデルに残す。
   当初予算は事業×歳出の節に集約済みで、参照は節マスタ ID、下位内訳は details_json。 #}
{%- set budget = kind == 'initial_expenditure_budget' -%}
{%- if budget -%}
select l.fiscal_line_id, l.dataset_id, d.fiscal_year, l.source_row, l.budget_item_id,
       l.amount, b.expenditure_setsu_id, b.line_granularity,
       b.account_path_json, b.dimensions_json, l.details_json,
       l.consolidation, l.counterpart_fund, l.cofog_code, l.cofog_status, l.cofog_basis
from {{ ref('fiscal_initial_expenditure_budget_lines') }} l
join {{ ref('fiscal_expenditure_budget_items') }} b using (budget_item_id)
join {{ ref('int_fiscal_datasets') }} d using (dataset_id)
where d.jurisdiction_code = '{{ code }}'
{%- else -%}
{%- set removed = ['phase_id', 'value', 'source_amount'] -%}
{%- if fiscal_amount_unit_is_column(code, 'expenditure') -%}
    {% do removed.append('source_amount_unit') %}
{%- endif -%}
{%- for level in var('fiscal_levels')[code]['expenditure'] if level in ['setsu', 'saisetsu', 'saisaisetsu'] -%}
    {% do removed.extend([level ~ '_code', level ~ '_label']) %}
{%- endfor -%}
select p.* exclude({{ removed | join(', ') }}), p.value as amount,
    l.cofog_code, l.cofog_status, l.cofog_basis, l.consolidation, l.counterpart_fund
from {{ ref('pkg_' ~ code ~ '__expenditure') }} p
join {{ ref('fiscal_' ~ ('initial_expenditure_budget_lines' if budget else 'settlement_expenditure_lines')) }} l
    using (fiscal_line_id, dataset_id)
join {{ ref('int_fiscal_datasets') }} d using (dataset_id)
where d.document_kind = 'settlement'
    and p.phase_id = 'executed'
{%- endif %}
{% endmacro %}
