{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132195/revenue_budget_changes.csv' (FORMAT CSV, HEADER TRUE)") }}
select l.* from {{ ref('api_fiscal_revenue_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'
