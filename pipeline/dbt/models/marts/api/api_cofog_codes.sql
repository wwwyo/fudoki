{{ api_model('cofog_codes') }}
select code, label, level, parent_code::varchar as parent_code
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/cofog_codes.json')
order by code
