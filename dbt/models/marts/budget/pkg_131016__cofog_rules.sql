{{ config(materialized = 'external', location = '../data/budget/datapackages/131016/cofog_rules.csv', format = 'csv') }}
-- COFOG の割り当て規則。**fudoki の判断そのもの**（規則も配るので、利用者は判断を検討できる）。
-- 説明と実装は macros/budget_package_judgment.sql。
{{ budget_package_cofog_rules('131016') }}
