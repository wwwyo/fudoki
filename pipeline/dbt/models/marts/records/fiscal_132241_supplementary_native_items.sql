{{ config(materialized='table') }}
select distinct budget_item_id, jurisdiction_code, fiscal_year, fund_code, fund_label,
       expenditure_setsu_id, line_granularity, account_path_json, dimensions_json,
       to_json([
         struct_pack(kind := 'hierarchy', level := 'moku', value := moku_label, nameSource := 'origin', basis := ''),
         struct_pack(kind := 'hierarchy', level := 'project', value := project_label, nameSource := 'origin', basis := '')
       ] || case when expenditure_setsu_id is null then [] else [
         struct_pack(kind := 'hierarchy', level := 'setsu', value := left_setsu_label,
                     nameSource := 'origin', basis := '同じ目の左節コード・名称と当該年度の法定節マスタの一致')
       ] end)::varchar as names_json,
       'unconfirmed'::varchar as initial_state
from {{ ref('int_132241__supplementary_native') }}
where observation_role = 'expenditure' and canonical_changes and phases_json = '["adjusted"]'
order by budget_item_id
