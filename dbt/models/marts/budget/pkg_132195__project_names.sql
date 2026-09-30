{{ config(materialized = 'external', location = '../data/budget/datapackages/132195/project_names.csv', format = 'csv') }}
-- 事業名の対応づけ。**fudoki の判断**（自治体は「大事業37 は○○のことだ」と言っていない）。
--
-- 原典の CSV は大事業を数字コードでしか持たず、名称は決算資料 PDF にしかない。
-- PDF は大事業コードを書いていないので、同じ目の中で金額が一致するものを対応づけている。
-- **どう決めたかは core_budget_project_names.sql に書いてある。**
--
-- ⚠️ **全部の大事業に名前が付くわけではない。** 一般会計 × 2020〜2023 の外には付かない
-- （PDF の事項別明細が一般会計だけで、決算ページが 2020年度以降しか無い）。
-- 金額が 0 の事業も、同じ目に何件も並んで区別できないため付かない。
-- カバレッジは tests/project_names_cover_budget.sql が毎回測る。
select
    fiscal_year,
    fund_code,
    kan_code,
    kou_code,
    moku_code,
    daijigyo_code,
    project_name,
    -- **判断の中身を読めるようにする。** どの金額で・どの丸めで・候補がいくつある中から当てたか。
    matched_thousand_yen,
    match_method,
    match_basis,
    candidate_count
from {{ ref('core_budget_project_names') }}
where jurisdiction_code = '132195'
order by fiscal_year, fund_code, cast(kan_code as integer), cast(kou_code as integer),
         cast(moku_code as integer), cast(daijigyo_code as integer)
