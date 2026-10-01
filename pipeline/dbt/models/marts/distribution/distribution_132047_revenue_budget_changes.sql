{{ fiscal_distribution_csv('132047', 'revenue_budget_changes') }}
select l.* from {{ ref('api_fiscal_revenue_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'
