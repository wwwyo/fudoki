{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/131016/expenditure_settlement_links.csv' (FORMAT CSV, HEADER TRUE)") }}
select l.* from {{ ref('api_fiscal_expenditure_settlement_links') }} l join {{ ref('api_fiscal_expenditure_budget_items') }} i using(budget_item_id) where i.jurisdiction_code='131016'
