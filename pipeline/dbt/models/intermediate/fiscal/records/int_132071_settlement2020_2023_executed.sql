-- Unit is printed 円 (multiplier 1). Judgment columns stay separate from original columns.
-- FY2020 uses legacy printed setsu codes preserved verbatim; master mapping stays NULL on conflict.
select s.*,
       case when unit='円' then amount_executed
            else error('Settlement2020-2023 printed unit identity differs') end as amount,
       'JPY' as currency,
       ms.expenditure_setsu_id as mapped_expenditure_setsu_id,
       case when ms.expenditure_setsu_id is not null then 'confirmed-printed-code-name-active-year'
            when s.printed_setsu_code is null then 'unconfirmed-blank-reserve-row'
            else 'unconfirmed-printed-name-master-conflict' end as legal_mapping_status,
       'unconfirmed' as project_setsu_linkage,
       to_json([
        struct_pack(level:='kan',code:=kan_code,label:=kan_name,nameSource:='origin'),
        struct_pack(level:='kou',code:=kou_code,label:=kou_name,nameSource:='origin'),
        struct_pack(level:='moku',code:=moku_code,label:=moku_name,nameSource:='origin'),
        struct_pack(level:='setsu',code:=printed_setsu_code,label:=printed_setsu_name,nameSource:='origin')
       ])::varchar as account_path_json,
       '[]'::varchar as dimensions_json,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__settlement2020_2023_financial') }} s
left join {{ ref('fiscal_expenditure_setsu_master') }} ms
  on try_cast(ms.code as integer)=try_cast(s.printed_setsu_code as integer)
 and ms.label=s.printed_setsu_name
 and s.fiscal_year>=coalesce(ms.valid_from_fiscal_year,-9999)
 and s.fiscal_year<=coalesce(ms.valid_to_fiscal_year,9999)
