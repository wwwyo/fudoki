-- **公表資料との突合。** 原典とは別の経路で作られた資料と照らす。
-- 款別で比べる。合計だけだと誤りが打ち消し合ったときに通ってしまう。
-- ⚠️ **公表値がある年度・予算段階だけを比べる。**
-- 全年度を合計して単年度の公表値と比べると、2年度目を足した時点で必ず落ちる。
with scope as (
    select distinct fiscal_year, 'approved' as phase_id from {{ ref('published_reference_meta') }}
),

ours as (
    select 'expenditure' as direction, kan_label, sum(source_amount) as amount
    from {{ ref('stg_132047__expenditure') }} as s
    inner join scope using (fiscal_year, phase_id)
    where s.fund_source = '01一般会計' group by 2
    union all
    select 'revenue', kan_label, sum(source_amount)
    from {{ ref('stg_132047__revenue') }} as s
    inner join scope using (fiscal_year, phase_id)
    where s.fund_source = '01一般会計' group by 2
)
select
    coalesce(o.direction, p.direction) as direction,
    coalesce(o.kan_label, p.kan_label) as kan_label,
    o.amount                           as ours,
    p.amount_thousand_yen              as published
from ours as o
full outer join {{ ref('published_reference') }} as p
    on o.direction = p.direction and o.kan_label = p.kan_label
where coalesce(o.amount, -1) is distinct from coalesce(p.amount_thousand_yen, -2)
