-- Per account, the subject-level sums must agree: moku sums equal kan sums, and for
-- accounts without moku nodes (132012介護・後期高齢者) kou sums equal kan sums.
-- Printed account totals do not exist as nodes in these tables, so the kan sum is
-- the account total. Compare one axis only; mixing axes double-counts.
-- A division table (所属, ADR 0030) may print its share of a 項 with no 目 under it
-- (281000 福祉局の2款1項 総務費): at the moku level that share counts as itself.
with account_sums as (
    select jurisdiction_code, fiscal_year, account_name,
        sum(amount_yen) filter (where node_kind = '款') as kan_sum,
        sum(amount_yen) filter (where node_kind = '項') as kou_sum,
        sum(amount_yen) filter (where node_kind = '目') as moku_sum,
        count(*) filter (where node_kind = '目') as moku_count
    from {{ ref('settlement_expenditure_node') }}
    where is_subject
    group by 1, 2, 3
), rows as (
    select * from {{ ref('int_fiscal__settlement_expenditure_rows') }}
), division_kou_without_moku as (
    select k.jurisdiction_code, k.fiscal_year, k.account_name, sum(k.amount_yen) as amount
    from rows k
    where k.division is not null and k.node_kind = '項' and k.axis_header = k.subject_axis
      and not exists (select 1 from rows m where m.source_table_key = k.source_table_key
                      and m.parent_node_key = k.node_key and m.node_kind = '目')
    group by 1, 2, 3
)
select jurisdiction_code, fiscal_year, account_name, 'account_level_sums' as failure,
    kan_sum, kou_sum, moku_sum
from account_sums
left join division_kou_without_moku d using (jurisdiction_code, fiscal_year, account_name)
where case when moku_count > 0 then moku_sum + coalesce(d.amount, 0) else kou_sum end is distinct from kan_sum
  and kan_sum is not null
  and (moku_count > 0 or kou_sum is not null)
