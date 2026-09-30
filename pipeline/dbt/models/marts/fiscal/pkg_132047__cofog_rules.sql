{{ config(materialized = 'external', location = env_var('FUDOKI_PACKAGE_DIR') ~ '/132047/cofog_rules.csv', format = 'csv') }}
-- COFOG の割り当て規則。**fudoki の判断そのもの**（規則も配るので、利用者は判断を検討できる）。
-- 説明と実装は macros/fiscal_package_judgment.sql。
{{ fiscal_package_cofog_rules('132047') }}
