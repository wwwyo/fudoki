{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132241/expenditure_budget_items.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('api_fiscal_expenditure_budget_items') }} where jurisdiction_code='132241'
