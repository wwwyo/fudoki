with observed as (
  select s.*, s.amount_delta * 1000::bigint as delta_yen,
         s.approval_date as effective_at,
         case when regexp_full_match(s.department_text, '〔[^0-9△,〔〕]+[△]?[0-9,]*〕')
              then regexp_extract(s.department_text, '〔([^0-9△,〔〕]+)', 1)
              else s.department_text end as department_label,
         m.expenditure_setsu_id,
         case when m.expenditure_setsu_id is not null then 'confirmed-printed-code-name-active-master'
              else 'unconfirmed' end as expenditure_setsu_status,
         to_json([
           struct_pack(level:='kan',code:=s.kan_code,label:='',nameSource:='origin'),
           struct_pack(level:='kou',code:=s.kou_code,label:='',nameSource:='origin'),
           struct_pack(level:='moku',code:=s.moku_code,label:=s.moku_label,nameSource:='origin'),
           struct_pack(level:='project',code:=s.project_code,label:=s.project_label,nameSource:='origin')
         ])::varchar as account_path_json,
         to_json([struct_pack(dimension:='department',code:='',label:=department_label)])::varchar as dimensions_json
  from {{ ref('stg_132195__supplementary_expenditure') }} s
  left join {{ ref('expenditure_setsu_map') }} mp
    on mp.jurisdiction_code=s.jurisdiction_code and mp.setsu_label=s.setsu_label and s.setsu_code is not null
  left join {{ ref('fiscal_expenditure_setsu_master') }} m
    on m.expenditure_setsu_id=mp.expenditure_setsu_id
   and try_cast(m.code as integer)=try_cast(s.setsu_code as integer)
   and m.label=s.setsu_label
   and s.fiscal_year>=coalesce(m.valid_from_fiscal_year,-9999)
   and s.fiscal_year<=coalesce(m.valid_to_fiscal_year,9999)
), identity as (
  select *,
    json_object('identityNamespace','supplementary-printed-target','jurisdiction',jurisdiction_code,
      'year',fiscal_year,'account',fund_label,'path',account_path_json::json,'dimensions',dimensions_json::json,
      'printedSetsuCode',setsu_code,'printedSetsuLabel',setsu_label,'sourceGrain',source_grain)::varchar as target_identity_json
  from observed
)
select *, {{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id,
       'unconfirmed'::varchar as initial_state
from identity
