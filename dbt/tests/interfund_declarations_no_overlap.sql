-- **1つの行に当たる宣言は1つだけ。** ワイルドカード行と詳細行が同じ行に
-- 当たると、どちらの宣言が効いたかで消去の意味が変わる（受け皿・根拠が違う）。
-- モデルは最も具体的な宣言を採って畳むが、競合する宣言自体は作らない —
-- 書き分けできない行を「どちらかに決まった」と扱うより、宣言側で直させる。
with hits as (
    select l.budget_line_id
    from {{ ref('interfund_transfers') }} as t
    join {{ ref('core_budget_lines') }} as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  = '*' or t.moku_code  = l.moku_code)
        and (t.setsu_code = '*' or t.setsu_code = l.setsu_code)
        and (t.amount_yen = '*' or t.amount_yen = cast(l.amount_yen as varchar))
    where t.direction = 'expenditure'
    group by all
    having count(*) > 1

    union all

    select l.budget_line_id
    from {{ ref('interfund_transfers') }} as t
    join {{ ref('core_revenue_lines') }} as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  = '*' or t.moku_code  = l.moku_code)
        and (t.setsu_code = '*' or t.setsu_code = l.setsu_code)
        and (t.amount_yen = '*' or t.amount_yen = cast(l.amount_yen as varchar))
    where t.direction = 'revenue'
    group by all
    having count(*) > 1
)

select budget_line_id, '複数の宣言に当たる' as problem from hits
