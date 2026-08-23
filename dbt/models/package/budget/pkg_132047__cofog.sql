{{ config(materialized = 'external', location = '../data/budget/datapackages/132047/cofog.csv', format = 'csv') }}
{{ budget_package_cofog('132047') }}
