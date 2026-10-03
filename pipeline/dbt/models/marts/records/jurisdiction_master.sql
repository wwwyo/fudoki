{{ config(materialized='table') }}
select jurisdiction_code, name, ocd_id
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/jurisdiction_master.json')
order by jurisdiction_code
