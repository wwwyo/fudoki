-- **COFOG の不変条件をまとめて見る。** どれか1つでも破れたら行が出る。
with e as (
    select c.*, s.source_amount
    from {{ ref('core_budget_cofog') }} as c
    inner join {{ ref('stg_132047__expenditure') }} as s using (budget_line_id)
)

-- 1. 原典の保存。全状態の合計が原典の合計に戻る（分類で金額が消えていない）
select '原典の保存' as invariant, sum(source_amount) as ours,
       (select sum(source_amount) from {{ ref('stg_132047__expenditure') }}) as expected
from e having sum(source_amount) <> (select sum(source_amount) from {{ ref('stg_132047__expenditure') }})

union all

-- 2. 適格母集団の保存。割当済み + 分類不能 = 対象外を除いた合計。
--    ⚠️ 同じ値どうしを比べる書き方にしない（以前それで空振りの検査を書いた）。
select '適格母集団の保存',
       sum(source_amount) filter (where cofog_status in ('assigned', 'unclassifiable')),
       sum(source_amount) filter (where cofog_status <> 'out-of-scope')
from e
having sum(source_amount) filter (where cofog_status in ('assigned', 'unclassifiable'))
    <> sum(source_amount) filter (where cofog_status <> 'out-of-scope')

union all

-- 3. 分類不能と対象外ではディビジョンが空。混ざると集計が壊れる
select '未割当でディビジョンが入っている', count(*), 0
from e where cofog_status <> 'assigned' and cofog_division <> ''
having count(*) > 0

union all

-- 4. 割当済みならディビジョンが 01〜10 のいずれか
select '割当済みなのにディビジョンが値域外', count(*), 0
from e where cofog_status = 'assigned'
  and cofog_division not in ('01','02','03','04','05','06','07','08','09','10')
having count(*) > 0

union all

-- 5. 消去する行には相手側がある。無いと連結の相手を辿れない
select '消去なのに相手側が無い', count(*), 0
from e where cofog_consolidation = 'eliminated' and cofog_counterpart_fund is null
having count(*) > 0
