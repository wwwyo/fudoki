{{ config(materialized = 'external', location = '../data/budget/datapackages/131016/cofog.csv', format = 'csv') }}
{{ budget_package_cofog('131016') }}
