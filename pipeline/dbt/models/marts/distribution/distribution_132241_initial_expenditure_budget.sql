{{ fiscal_distribution_csv('132241', 'initial_expenditure_budget') }}
select p.* exclude(phase_id,value,source_amount ,source_amount_unit),p.value as amount from {{ ref('pkg_132241__expenditure') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='budget' and p.phase_id='approved'
