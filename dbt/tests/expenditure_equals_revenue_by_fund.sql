-- **歳出と歳入の交差検算（会計ごと）。**
--
-- ⚠️ **一般の不変条件ではない。** 三鷹市の令和6年度当初予算について、
-- 同一の会計・年度・予算段階・収録範囲で成立することを実測で確認した条件付き検算。
-- 決算・企業会計・補正差分・会計範囲の異なる抽出では成立しない。
-- 団体を増やすときは、まずこれが成立するかを実測してから有効にする。
with e as (select fund_label, sum(source_amount) as amount from {{ ref('stg_132047__expenditure') }} group by 1),
     r as (select fund_label, sum(source_amount) as amount from {{ ref('stg_132047__revenue') }} group by 1)
select coalesce(e.fund_label, r.fund_label) as fund, e.amount as 歳出, r.amount as 歳入
from e full outer join r using (fund_label)
where coalesce(e.amount, -1) is distinct from coalesce(r.amount, -2)
