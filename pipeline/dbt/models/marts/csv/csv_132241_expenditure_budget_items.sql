{{ fiscal_csv('132241', 'expenditure_budget_items') }}
select * from {{ ref('fiscal_expenditure_budget_items') }} where jurisdiction_code='132241'
