{{ config(materialized='table') }}
select budget_item_id, jurisdiction_code, fiscal_year, fund_code, fund_label,
       expenditure_setsu_id, line_granularity, account_path_json, dimensions_json,
       to_json([
         struct_pack(kind := 'hierarchy', level := 'moku', value := moku_label, nameSource := 'origin', basis := ''),
         struct_pack(kind := 'hierarchy', level := 'project', value := project_label, nameSource := 'origin', basis := '')
       ])::varchar as names_json,
       'unconfirmed'::varchar as initial_state
from {{ ref('int_131016__supplementary_native') }}
where record_kind = 'project_delta' and canonical_changes and phases_json = '["adjusted"]'
order by budget_item_id
