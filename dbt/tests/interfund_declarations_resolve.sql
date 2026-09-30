-- **宣言した会計間移転が実際に収録済みの行に当たるか。**
-- 当たらない宣言は、年度が変わって科目や金額がずれた「古い宣言」。
-- 消去されるはずの行が retained に残ると、対の片側だけ消えて合計が壊れる。
with e as (
    select t.*, l.budget_line_id
    from {{ ref('interfund_transfers') }} as t
    left join {{ ref('core_budget_lines') }} as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  = '*' or t.moku_code  = l.moku_code)
        and (t.setsu_code = '*' or t.setsu_code = l.setsu_code)
        and (t.amount_yen = '*' or t.amount_yen = cast(l.amount_yen as varchar))
    where t.direction = 'expenditure'
),

r as (
    select t.*, l.budget_line_id
    from {{ ref('interfund_transfers') }} as t
    left join {{ ref('core_revenue_lines') }} as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  = '*' or t.moku_code  = l.moku_code)
        and (t.setsu_code = '*' or t.setsu_code = l.setsu_code)
        and (t.amount_yen = '*' or t.amount_yen = cast(l.amount_yen as varchar))
    where t.direction = 'revenue'
)

select jurisdiction_code, fiscal_year, direction, fund_label, kan_code, kou_code,
       moku_code, setsu_code, amount_yen, counterpart_fund
from (select * from e union all select * from r)
where budget_line_id is null
