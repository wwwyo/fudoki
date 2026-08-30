-- **COFOG の不変条件をまとめて見る。** どれか1つでも破れたら行が出る。
-- ⚠️ 金額は円で見る（`amount_yen`）。団体で原典の単位が違うので、
-- source_amount のまま足すと千円と円が混ざった合計になる。
with e as (
    select c.*, s.amount_yen
    from {{ ref('core_budget_cofog') }} as c
    inner join {{ ref('core_budget_lines') }} as s using (budget_line_id)
)

-- 1. 原典の保存。全状態の合計が原典の合計に戻る（分類で金額が消えていない）
select '原典の保存' as invariant, sum(amount_yen) as ours,
       (select sum(amount_yen) from {{ ref('core_budget_lines') }}) as expected
from e having sum(amount_yen) <> (select sum(amount_yen) from {{ ref('core_budget_lines') }})

union all

-- 2. 適格母集団の保存。割当済み + 分類不能 = 対象外を除いた合計。
--    ⚠️ 同じ値どうしを比べる書き方にしない（以前それで空振りの検査を書いた）。
select '適格母集団の保存',
       sum(amount_yen) filter (where cofog_status in ('assigned', 'unclassifiable')),
       sum(amount_yen) filter (where cofog_status <> 'out-of-scope')
from e
having sum(amount_yen) filter (where cofog_status in ('assigned', 'unclassifiable'))
    <> sum(amount_yen) filter (where cofog_status <> 'out-of-scope')

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

-- 5. 階層が矛盾していない。group は division の下、class は group の下でなければならない。
--    ⚠️ **粒度が粗いこと自体は誤りではない**（款の名称だけで決まる規則は division 止まり）。
--    誤りなのは、下位が入っているのに上位と食い違っていることのほう。
--    ⚠️ これは検査3（未割当ならディビジョンが空）と組んで、**未割当なのに group / class が
--    入っている**ケースも捕らえる（division が空のまま group が `04.5` なら1つ目の条件で落ちる）。
select 'COFOG の階層が食い違っている', count(*), 0
from e
where (cofog_group <> '' and split_part(cofog_group, '.', 1) <> cofog_division)
   or (cofog_class <> '' and not starts_with(cofog_class, cofog_group || '.'))
   or (cofog_class <> '' and cofog_group = '')
having count(*) > 0

union all

-- 6. 消去する行には相手側がある。無いと連結の相手を辿れない
select '消去なのに相手側が無い', count(*), 0
from e where cofog_consolidation = 'eliminated' and cofog_counterpart_fund is null
having count(*) > 0
