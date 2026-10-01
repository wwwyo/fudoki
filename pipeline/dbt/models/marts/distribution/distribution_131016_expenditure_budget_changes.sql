{{ fiscal_distribution_csv('131016', 'expenditure_budget_changes') }}
select l.* exclude(cofog_code,cofog_status,cofog_basis) from {{ ref('api_fiscal_expenditure_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'
