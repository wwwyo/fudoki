{{ fiscal_distribution_csv('132195', 'settlement_expenditure_cofog') }}
select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'
