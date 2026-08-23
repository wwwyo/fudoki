{{ config(materialized = 'external', location = '../data/budget/datapackages/132195/cofog.csv', format = 'csv') }}
{{ budget_package_cofog('132195') }}
