{{ config(materialized = 'external', location = '../data/budget/datapackages/132047/cofog.csv', format = 'csv') }}
-- COFOG の割当。**fudoki の判断**（自治体が言っていない分類を付け加えている）。
-- 説明と実装は macros/budget_package_judgment.sql。
{{ budget_package_cofog('132047') }}
