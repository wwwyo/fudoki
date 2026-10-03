{{ config(materialized='table') }}
select h.budget_item_id, s.fiscal_line_id as settlement_line_id,
       'confirmed' as match_status, 'komae-2023-' || h.target_key as match_group_id,
       '一般会計・同年度の款項目の集合対応。事業×歳出の節は未確認。決算CSVと決算書の目総額が一致' as basis
from {{ ref('int_fiscal_budget_history') }} h
join {{ ref('stg_132195__expenditure') }} s
  on h.jurisdiction_code=s.jurisdiction_code and h.fiscal_year=s.fiscal_year
 and h.fund_code=s.fund_code and h.kan_code=s.kan_code and h.kou_code=s.kou_code and h.moku_code=s.moku_code
where h.record_kind='initial'
order by budget_item_id, settlement_line_id
