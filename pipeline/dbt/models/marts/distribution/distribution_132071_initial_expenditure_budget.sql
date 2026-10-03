{{ fiscal_distribution_csv('132071', 'initial_expenditure_budget') }}
select l.fiscal_line_id, l.dataset_id, d.fiscal_year, l.source_row, l.budget_item_id,
       l.amount, b.expenditure_setsu_id, b.line_granularity,
       b.account_path_json, b.dimensions_json, l.details_json,
       l.consolidation, l.counterpart_fund, l.cofog_code, l.cofog_status, l.cofog_basis
from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l
join {{ ref('api_fiscal_expenditure_budget_items') }} b using (budget_item_id)
join {{ ref('int_fiscal_datasets') }} d using (dataset_id)
where d.jurisdiction_code = '132071'
