select jurisdiction_code, name as name_snapshot, ocd_id as ocd_id_snapshot, caveats_json
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/jurisdictions.json') j
where exists (select 1 from {{ ref('int_fiscal_datasets') }} d where d.jurisdiction_code=j.jurisdiction_code)
order by jurisdiction_code
