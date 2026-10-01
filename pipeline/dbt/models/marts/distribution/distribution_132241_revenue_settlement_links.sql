{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132241/revenue_settlement_links.csv' (FORMAT CSV, HEADER TRUE)") }}
select l.* from {{ ref('api_fiscal_revenue_settlement_links') }} l join {{ ref('api_fiscal_revenue_budget_items') }} i using(budget_item_id) where i.jurisdiction_code='132241'
