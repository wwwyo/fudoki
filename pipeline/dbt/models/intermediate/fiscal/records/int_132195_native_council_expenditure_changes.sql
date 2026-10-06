with printed as (
  select s.*,
       case s.setsu_label
         when '負担金,補助及び交付金' then '負担金、補助及び交付金'
         when '負担金補助及び交付金' then '負担金、補助及び交付金'
         when '償還金,利子及び割引料' then '償還金、利子及び割引料'
         when '償還金利子及び割引料' then '償還金、利子及び割引料'
         when '補償,補填及び賠償金' then '補償、補填及び賠償金'
         else s.setsu_label end as full_legal_setsu_label
  from {{ ref('stg_132195__native_council_approved_detail') }} s
), observed as (
  select s.*, s.amount_delta * 1000::bigint as delta_yen,
         s.effective_date as effective_at,
         case when regexp_full_match(s.department_text, '〔[^0-9△,〔〕]+[△]?[0-9,]*〕')
              then regexp_extract(s.department_text, '〔([^0-9△,〔〕]+)', 1)
              else s.department_text end as department_label,
         m.expenditure_setsu_id,
         case when m.expenditure_setsu_id is not null then 'confirmed-printed-code-full-name-active-master'
              else 'unconfirmed' end as expenditure_setsu_status,
         to_json([
           struct_pack(level:='kan',code:=s.kan_code,label:='',nameSource:='origin'),
           struct_pack(level:='kou',code:=s.kou_code,label:='',nameSource:='origin'),
           struct_pack(level:='moku',code:=s.moku_code,label:=s.moku_label,nameSource:='origin'),
           struct_pack(level:='project',code:=s.project_code,label:=s.project_label,nameSource:='origin')
         ])::varchar as account_path_json,
         to_json([struct_pack(dimension:='department',code:='',label:=department_label)])::varchar as dimensions_json
  from printed s
  left join {{ ref('fiscal_expenditure_setsu_master') }} m
    on s.setsu_code is not null
   and try_cast(m.code as integer)=try_cast(s.setsu_code as integer)
   and m.label=s.full_legal_setsu_label
   and s.fiscal_year>=coalesce(m.valid_from_fiscal_year,-9999)
   and s.fiscal_year<=coalesce(m.valid_to_fiscal_year,9999)
), identity as (
  select *,
    json_object('identityNamespace','supplementary-printed-target','jurisdiction',jurisdiction_code,
      'year',fiscal_year,'account',fund_label,'path',account_path_json::json,'dimensions',dimensions_json::json,
      'printedSetsuCode',setsu_code,'printedSetsuLabel',setsu_label,'sourceGrain',source_grain)::varchar as target_identity_json
  from observed
)
select c.*, {{ fiscal_budget_item_id('c.target_identity_json') }} as native_namespace_budget_item_id,
       coalesce(i.budget_item_id, existing.budget_item_id, {{ fiscal_budget_item_id('c.target_identity_json') }}) as budget_item_id,
       i.fiscal_line_id as exact_initial_fiscal_line_id,
       i.supplementary_compatibility_identity_json as exact_initial_compatibility_identity_json,
       existing.target_identity_json as exact_existing_target_identity_json,
       existing.fiscal_line_id as exact_existing_fiscal_line_id,
       case when i.budget_item_id is not null then 'recorded' else 'unconfirmed' end as initial_state
from identity c
left join {{ ref('int_132195_initial_detail') }} i
  on c.target_identity_json=i.supplementary_compatibility_identity_json
left join (
 select target_identity_json,budget_item_id,min(fiscal_line_id) as fiscal_line_id
 from (
  select target_identity_json,budget_item_id,fiscal_line_id from {{ ref('int_supplementary_expenditure_changes') }}
  union all
  select target_identity_json,budget_item_id,fiscal_line_id from {{ ref('int_132195_council_expenditure_changes') }}
 ) old_targets group by target_identity_json,budget_item_id
) existing on c.target_identity_json=existing.target_identity_json
-- Whole exact original-grain identity only. No label-only joins, date fallback,
-- invented initial amount or rebasing of existing targets.
