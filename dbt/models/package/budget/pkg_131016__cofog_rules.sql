{{ config(materialized = 'external', location = '../data/budget/datapackages/131016/cofog_rules.csv', format = 'csv') }}
{{ budget_package_cofog_rules('131016') }}
