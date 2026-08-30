{{ config(materialized = 'external', location = '../data/budget/datapackages/132241/cofog.csv', format = 'csv') }}
{{ budget_package_cofog('132241') }}
