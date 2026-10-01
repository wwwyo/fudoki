{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132241/expenditure_budget_change_cofog.csv' (FORMAT CSV, HEADER TRUE)") }}
select l.change_id,l.cofog_code,l.cofog_status,l.cofog_basis from {{ ref('api_fiscal_expenditure_budget_changes') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'
