{{ config(materialized='table') }}
select s.*, s.delta_amount*1000::bigint as amount_delta,
       'c-' || sha256(s.fiscal_line_id) as change_id, h.budget_item_id,
       d.effective_at, d.amendment_number,
       'nonadditive-moku-reference'::varchar as observation_role,
       exists(select 1 from {{ ref('int_supplementary_expenditure_changes') }} h
         where h.jurisdiction_code=s.jurisdiction_code and h.fiscal_year=s.fiscal_year
           and h.fund_label=s.fund_label and h.amendment_number=d.amendment_number) as superseded_by_detail
from {{ ref('stg_132195__budget_history') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') d using(dataset_id)
left join {{ ref('int_fiscal_budget_history') }} h on h.fiscal_line_id=s.fiscal_line_id and h.record_kind='change'
where s.record_kind='change'
order by s.fiscal_line_id
