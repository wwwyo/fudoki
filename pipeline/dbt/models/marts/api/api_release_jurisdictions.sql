{{ api_model('release_jurisdictions') }}
select jurisdiction_code, name as name_snapshot, ocd_id as ocd_id_snapshot, caveats_json
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/jurisdictions.json')
order by jurisdiction_code
