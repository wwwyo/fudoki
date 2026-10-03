{{ fiscal_csv('131016', 'settlement_revenue') }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_131016__revenue') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='settlement' and p.phase_id='executed'
