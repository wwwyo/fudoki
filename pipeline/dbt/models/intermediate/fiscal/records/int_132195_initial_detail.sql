with observed as (
  select s.*, s.amount_initial * 1000::bigint as initial_yen,
         case when regexp_full_match(s.department_text, '〔[^0-9△,〔〕]+[△]?[0-9,]*〕')
              then regexp_extract(s.department_text, '〔([^0-9△,〔〕]+)', 1)
              else s.department_text end as department_label,
         m.expenditure_setsu_id,
         case when m.expenditure_setsu_id is not null then 'confirmed-printed-code-name-active-master'
              else 'unconfirmed' end as expenditure_setsu_status,
         to_json([
           struct_pack(level:='kan',code:=s.kan_code,label:=s.kan_label,nameSource:='origin'),
           struct_pack(level:='kou',code:=s.kou_code,label:=s.kou_label,nameSource:='origin'),
           struct_pack(level:='moku',code:=s.moku_code,label:=s.moku_label,nameSource:='origin'),
           struct_pack(level:='project',code:=s.project_code,label:=s.project_label,nameSource:='origin')
         ])::varchar as observed_account_path_json,
         {# Existing supplementary namespace never had kan/kou label fields.
            This explicit projection is solely for equivalence to those IDs;
            full original labels survive above, in raw, and in public details. #}
         to_json([
           struct_pack(level:='kan',code:=s.kan_code,label:='',nameSource:='origin'),
           struct_pack(level:='kou',code:=s.kou_code,label:='',nameSource:='origin'),
           struct_pack(level:='moku',code:=s.moku_code,label:=s.moku_label,nameSource:='origin'),
           struct_pack(level:='project',code:=s.project_code,label:=s.project_label,nameSource:='origin')
         ])::varchar as supplementary_compatibility_path_json,
         to_json([struct_pack(dimension:='department',code:='',label:=department_label)])::varchar as dimensions_json
  from {{ ref('stg_132195__initial_detail') }} s
  left join {{ ref('expenditure_setsu_map') }} mp
    on mp.jurisdiction_code=s.jurisdiction_code and mp.setsu_label=s.setsu_label and s.setsu_code is not null
  left join {{ ref('fiscal_expenditure_setsu_master') }} m
    on m.expenditure_setsu_id=mp.expenditure_setsu_id
   and try_cast(m.code as integer)=try_cast(s.setsu_code as integer)
   and m.label=s.setsu_label
   and s.fiscal_year>=coalesce(m.valid_from_fiscal_year,-9999)
   and s.fiscal_year<=coalesce(m.valid_to_fiscal_year,9999)
), identities as (
 select *,
    json_object('identityNamespace','initial-printed-target','jurisdiction',jurisdiction_code,
      'year',fiscal_year,'account',fund_label,'path',observed_account_path_json::json,'dimensions',dimensions_json::json,
      'printedSetsuCode',setsu_code,'printedSetsuLabel',setsu_label,'sourceGrain',source_grain)::varchar as initial_target_identity_json,
    json_object('identityNamespace','supplementary-printed-target','jurisdiction',jurisdiction_code,
      'year',fiscal_year,'account',fund_label,'path',supplementary_compatibility_path_json::json,'dimensions',dimensions_json::json,
      'printedSetsuCode',setsu_code,'printedSetsuLabel',setsu_label,'sourceGrain',source_grain)::varchar as supplementary_compatibility_identity_json
 from observed
), distinct_changed_targets as (
 select distinct budget_item_id,target_identity_json from {{ ref('int_supplementary_expenditure_changes') }}
)
select i.*, {{ fiscal_budget_item_id('initial_target_identity_json') }} as initial_namespace_budget_item_id,
       coalesce(c.budget_item_id, {{ fiscal_budget_item_id('initial_target_identity_json') }}) as budget_item_id,
       case when c.budget_item_id is not null then i.supplementary_compatibility_path_json
            else i.observed_account_path_json end as account_path_json,
       case when c.budget_item_id is not null then 'confirmed-exact-printed-identity-including-sourceGrain'
            else 'initial-only-observed-target' end as namespace_equivalence_status,
       'recorded'::varchar as initial_state
from identities i
left join distinct_changed_targets c
  on c.target_identity_json=i.supplementary_compatibility_identity_json
