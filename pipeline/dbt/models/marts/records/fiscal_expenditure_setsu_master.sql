{{ config(materialized='table') }}
select expenditure_setsu_id, code, label,
       valid_from_fiscal_year::integer as valid_from_fiscal_year,
       valid_to_fiscal_year::integer as valid_to_fiscal_year,
       legal_basis
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/fiscal_expenditure_setsu_master.json')
order by expenditure_setsu_id
