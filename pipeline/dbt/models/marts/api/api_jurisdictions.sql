{{ api_model('jurisdictions') }}
select jurisdiction_code, name, ocd_id
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/jurisdictions.json')
order by jurisdiction_code
