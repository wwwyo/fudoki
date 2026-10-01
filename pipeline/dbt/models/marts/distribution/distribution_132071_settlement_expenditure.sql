{{ fiscal_distribution_csv('132071', 'settlement_expenditure') }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_132071__expenditure') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='settlement' and p.phase_id='executed'
