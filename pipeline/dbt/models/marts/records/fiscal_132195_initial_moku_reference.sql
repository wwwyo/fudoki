{{ config(materialized='table') }}
select s.*,h.budget_item_id,h.initial_amount*1000::bigint as amount_initial,
       'nonadditive-initial-moku-reference'::varchar as observation_role,
       exists(select 1 from {{ ref('int_132195_initial_detail') }} d
          where d.jurisdiction_code=s.jurisdiction_code and d.fiscal_year=s.fiscal_year
          and d.fund_label=s.fund_label) as superseded_by_full_initial_detail
from {{ ref('stg_132195__budget_history') }} s
join {{ ref('int_fiscal_budget_history') }} h using(fiscal_line_id)
where s.record_kind='initial'
order by s.fiscal_line_id
