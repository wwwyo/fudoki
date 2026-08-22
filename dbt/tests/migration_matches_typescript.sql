-- **移行の正しさを測る検査。TS 版を落とすまでの一時的なもの。**
--
-- 規則35本は TypeScript の述語から seed へ手で書き写した。書き写しは必ず間違えるので、
-- 既存の出力を正解セットにして1行ずつ突き合わせる。
-- rule_id まで比べるのは、たまたま同じ分類に落ちただけの一致を通さないため。
--
-- TS 版を削除するときに、この検査も一緒に消す。
-- そのとき何が保証されなくなるかは AGENTS.md の Caveats に残す。
with oracle as (
    select
        cast(source_row as bigint)       as source_row,
        cofog_status,
        coalesce(cofog_division_code, '') as division,
        cofog_consolidation,
        cofog_decided_at_level,
        cofog_rule_id
    from read_csv('../data/packages/132047/2024/expenditure-cofog.csv', header = true, all_varchar = true)
)

select o.source_row, o.cofog_rule_id as oracle_rule, c.cofog_rule_id as dbt_rule
from oracle as o
full outer join {{ ref('core_budget_cofog') }} as c using (source_row)
where o.cofog_status is distinct from c.cofog_status
   or o.division is distinct from c.cofog_division
   or o.cofog_consolidation is distinct from c.cofog_consolidation
   or o.cofog_decided_at_level is distinct from c.cofog_decided_at_level
   or o.cofog_rule_id is distinct from c.cofog_rule_id
