{{ config(materialized = 'external', location = '../data/budget/datapackages/132195/cofog_rules.csv', format = 'csv') }}
{{ budget_package_cofog_rules('132195') }}
