{{ fiscal_distribution_csv('132047', 'expenditure_budget_change_cofog') }}
select l.change_id,l.cofog_code,l.cofog_status,l.cofog_basis from {{ ref('api_fiscal_expenditure_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'
