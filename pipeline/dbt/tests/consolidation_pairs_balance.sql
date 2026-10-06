-- **連結の消去が歳出側と歳入側で釣り合うこと。**
--
-- 行と行は1対1に対応しない（細々節の切り方が両者で違う）。
-- 同じ年度・資料種類の会計の対どうしで突き合わせる。年度間や予算・決算間の
-- 差額を相殺して、片側の消去漏れを見逃してはいけない。
-- 片側だけ消去すると全会計の合計が壊れるが、合計だけ見ていると気づけない。
--
-- ⚠️ **繰入金の出し手を原典から読めない団体は宣言で消去する。** 狛江市は
-- 科目が数字コードだけで出し手を原典から決められないので、対を検算した行だけを
-- interfund_transfers.csv に宣言して消去する（core_revenue_consolidation を参照）。
-- 宣言が無い移転は retained のまま残る。
-- 「消去が1件も無い」は全団体での空振り防止なので、団体ごとに見てはいけない
-- （消去できない団体があると落ちる）。突合の対象は消去のある団体。
with paid as (
    select
        e.jurisdiction_code      as jurisdiction,
        e.fiscal_year, e.document_kind,
        c.cofog_counterpart_fund as to_fund,
        e.fund_label             as from_fund,
        sum(e.amount_yen)        as amount
    from {{ ref('core_fiscal_cofog') }} as c
    inner join {{ ref('core_fiscal_lines') }} as e using (fiscal_line_id)
    where c.cofog_consolidation = 'eliminated'
    group by 1, 2, 3, 4, 5
),

received as (
    select
        r.jurisdiction_code      as jurisdiction,
        r.fiscal_year, r.document_kind,
        r.fund_label             as to_fund,
        c.cofog_counterpart_fund as from_fund,
        sum(r.amount_yen)        as amount
    from {{ ref('core_revenue_consolidation') }} as c
    inner join {{ ref('core_revenue_lines') }} as r using (fiscal_line_id)
    where c.cofog_consolidation = 'eliminated'
    group by 1, 2, 3, 4, 5
)

-- ⚠️ 空振り防止。両側とも0件でも「差が無い」は成立するので、
-- 消去が1件も無い状態を落とす。以前これで自分自身と比べる検査を書いた。
select '(消去が1件も無い)' as jurisdiction, null::integer as fiscal_year, null as document_kind, null as from_fund, null as to_fund,
       null as paid, null as received
where not exists (select 1 from paid)

union all

select
    coalesce(p.jurisdiction, v.jurisdiction) as jurisdiction,
    coalesce(p.fiscal_year, v.fiscal_year) as fiscal_year,
    coalesce(p.document_kind, v.document_kind) as document_kind,
    coalesce(p.from_fund, v.from_fund) as from_fund,
    coalesce(p.to_fund, v.to_fund)     as to_fund,
    p.amount                           as paid,
    v.amount                           as received
from paid as p
full outer join received as v using (jurisdiction, fiscal_year, document_kind, to_fund, from_fund)
where coalesce(p.amount, -1) is distinct from coalesce(v.amount, -2)
