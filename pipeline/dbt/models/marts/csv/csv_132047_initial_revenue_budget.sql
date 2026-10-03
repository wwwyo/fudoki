{{ fiscal_csv('132047', 'initial_revenue_budget') }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_132047__revenue') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='budget' and p.phase_id='approved'
