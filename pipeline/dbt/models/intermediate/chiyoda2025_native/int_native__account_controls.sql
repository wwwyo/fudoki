-- 印刷歳出合計との独立統制。欠損の診断列は 0 ではなく NULL のまま残す。
with moku as (
  select account, sum(observed_amount) as moku_sum, count(*) as moku_rows
  from {{ ref('stg_native__moku_controls') }} where role='moku-control' group by account
),
legal as (
  select account, sum(observed_amount) as legal_sum, count(*) filter (observed_amount is null) as legal_nulls
  from {{ ref('stg_native__legal_amounts') }} group by account
),
expl as (
  select account, sum(observed_amount) as explanation_sum, count(*) as explanation_rows
  from {{ ref('stg_native__explanation_amounts') }} group by account
)
select m.account, moku_sum, moku_rows, legal_sum, legal_nulls,
       explanation_sum, explanation_rows
from moku m left join legal using(account) left join expl using(account)
