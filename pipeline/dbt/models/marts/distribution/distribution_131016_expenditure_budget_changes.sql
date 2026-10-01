{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/131016/expenditure_budget_changes.csv' (FORMAT CSV, HEADER TRUE)") }}
select l.* exclude(cofog_code,cofog_status,cofog_basis) from {{ ref('api_fiscal_expenditure_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'
