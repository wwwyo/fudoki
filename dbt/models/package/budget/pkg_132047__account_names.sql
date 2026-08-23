{{ config(materialized = 'external', location = '../data/budget/datapackages/132047/account_names.csv', format = 'csv') }}
-- 科目（款・項・目）の名称と、法定マスタへの対応。**fudoki の判断を含む。**
--
-- 名称の出所は name_source が言う（source-csv = 原典の文字列そのまま /
-- settlement-pdf = 決算書 PDF の見出しから fudoki が解決した）。
-- master_* は地方自治法施行規則 別記の区分への対応で、**コードは団体ごとに
-- 法定とずれる**（法定の款11 災害復旧費を持たない市では以降が詰まる）ため、
-- コードではなくこの対応を介して団体をまたいで比較する。
-- master_kind = addition は法定に無い団体固有の区分（様式の備考1が認める追加）。
-- 特別会計と歳入に master_* が付かないのは様式の対象が一般会計の歳出だけのため。
select
    fiscal_year, direction, fund_code, fund_label,
    kan_code, kan_name, kou_code, kou_name, moku_code, moku_name,
    name_source,
    master_kan_code, master_kan_name, master_kou_code, master_kou_name,
    master_kind, master_basis
from {{ ref('core_budget_accounts') }}
where jurisdiction_code = '132047'
order by fiscal_year, direction, fund_code, cast(kan_code as integer),
         cast(kou_code as integer), cast(moku_code as integer)
