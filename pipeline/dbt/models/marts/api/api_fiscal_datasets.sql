{{ api_model('fiscal_datasets') }}
select * exclude(phases_json), null::integer as amendment_number, null::varchar as effective_at, case when document_kind='settlement' then 'executed' when document_kind='budget' then 'initial' else null end as source_amount_kind, '{"budgetHistory":"unconfirmed"}'::varchar as coverage_json from {{ ref('int_fiscal_datasets') }} order by dataset_id
