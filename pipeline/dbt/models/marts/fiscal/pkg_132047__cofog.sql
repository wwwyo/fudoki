{{ config(materialized = 'external', location = env_var('FUDOKI_PACKAGE_DIR') ~ '/132047/cofog.csv', format = 'csv') }}
-- COFOG の割当。**fudoki の判断**（自治体が言っていない分類を付け加えている）。
-- 説明と実装は macros/fiscal_package_judgment.sql。
{{ fiscal_package_cofog('132047') }}
