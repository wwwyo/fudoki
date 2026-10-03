{{ fiscal_csv('132047', 'expenditure_budget_items') }}
select * from {{ ref('fiscal_expenditure_budget_items') }} where jurisdiction_code='132047'
