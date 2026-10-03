select s.*, d.effective_at, d.amendment_number,
       s.initial_amount * 1000 as initial_yen, s.delta_amount * 1000 as delta_yen,
       s.before_amount * 1000 as before_yen, s.after_amount * 1000 as after_yen,
       s.kan_code || '-' || s.kou_code || '-' || s.moku_code as target_key,
       'b-' || sha256(i.fiscal_line_id) as budget_item_id
from {{ ref('stg_132195__budget_history') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') d using (dataset_id)
join {{ ref('stg_132195__budget_history') }} i
  on i.record_kind='initial' and i.jurisdiction_code=s.jurisdiction_code and i.fiscal_year=s.fiscal_year
 and i.fund_code=s.fund_code and i.kan_code=s.kan_code and i.kou_code=s.kou_code and i.moku_code=s.moku_code
where s.record_kind in ('initial','change')
