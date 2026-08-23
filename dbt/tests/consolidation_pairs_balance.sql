-- **連結の消去が歳出側と歳入側で釣り合うこと。**
--
-- 行と行は1対1に対応しない（細々節の切り方が両者で違う）。
-- 厳密に一致するのは会計の対どうしの合計なので、そこで突き合わせる。
-- 片側だけ消去すると全会計の合計が壊れるが、合計だけ見ていると気づけない。
--
-- ⚠️ **消去そのものが成立しない団体がある。** 狛江市は繰入金がどの会計から来たかを
-- 原典から決められないので1件も消去しない（core_revenue_consolidation を参照）。
-- 下の「消去が1件も無い」を団体ごとに見ると狛江市で落ちるので、
-- 消去のある団体（＝歳出側に消去がある団体）だけを突合の対象にする。
with paid as (
    select
        e.jurisdiction_code      as jurisdiction,
        c.cofog_counterpart_fund as to_fund,
        e.fund_label             as from_fund,
        sum(e.amount_yen)        as amount
    from {{ ref('core_budget_cofog') }} as c
    inner join {{ ref('core_budget_lines') }} as e using (budget_line_id)
    where c.cofog_consolidation = 'eliminated'
    group by 1, 2, 3
),

received as (
    select
        r.jurisdiction_code      as jurisdiction,
        r.fund_label             as to_fund,
        c.cofog_counterpart_fund as from_fund,
        sum(r.amount_yen)        as amount
    from {{ ref('core_revenue_consolidation') }} as c
    inner join {{ ref('core_revenue_lines') }} as r using (budget_line_id)
    where c.cofog_consolidation = 'eliminated'
    group by 1, 2, 3
)

-- ⚠️ 空振り防止。両側とも0件でも「差が無い」は成立するので、
-- 消去が1件も無い状態を落とす。以前これで自分自身と比べる検査を書いた。
select '(消去が1件も無い)' as jurisdiction, null as from_fund, null as to_fund,
       null as paid, null as received
where not exists (select 1 from paid)

union all

select
    coalesce(p.jurisdiction, v.jurisdiction) as jurisdiction,
    coalesce(p.from_fund, v.from_fund) as from_fund,
    coalesce(p.to_fund, v.to_fund)     as to_fund,
    p.amount                           as paid,
    v.amount                           as received
from paid as p
full outer join received as v using (jurisdiction, to_fund, from_fund)
where coalesce(p.amount, -1) is distinct from coalesce(v.amount, -2)
