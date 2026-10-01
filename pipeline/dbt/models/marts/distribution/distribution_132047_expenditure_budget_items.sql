{{ fiscal_distribution_csv('132047', 'expenditure_budget_items') }}
select * from {{ ref('api_fiscal_expenditure_budget_items') }} where jurisdiction_code='132047'
