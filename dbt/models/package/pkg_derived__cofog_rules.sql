{{ config(materialized = 'external', location = '../data/packages/derived/cofog_rules.csv', format = 'csv') }}
-- 割り当て規則そのものを配る。**判断の中身を読めるようにするため。**
--
-- 派生の各行は cofog_rule_id でここを指す。根拠を行に複製せずに済むうえ、
-- 「どういう規則で決めたのか」を35行読むだけで確かめられる。
-- 分類結果だけを配ると、利用者は結果を検算できても判断を検討できない。
select
    priority,
    rule_id,
    applies_to,
    match_fund,
    match_kan,
    match_kou,
    match_moku,
    moku_mode,
    match_setsu,
    status,
    division,
    consolidation,
    decided_at_level,
    counterpart_fund,
    basis
from {{ ref('cofog_rules') }}
order by priority
