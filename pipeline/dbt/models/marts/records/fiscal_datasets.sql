{{ config(materialized='table') }}
select d.* exclude(phases_json), h.amendment_number, h.effective_at,
       case when d.document_kind='settlement' then 'executed' when d.document_kind='budget' then 'initial' else 'supplementary' end as source_amount_kind,
       '{"budgetHistory":"unconfirmed"}'::varchar as coverage_json
from {{ ref('int_fiscal_datasets') }} d
left join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h using(dataset_id)
order by dataset_id
