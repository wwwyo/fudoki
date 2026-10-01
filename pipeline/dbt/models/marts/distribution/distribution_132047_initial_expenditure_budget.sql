{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132047/initial_expenditure_budget.csv' (FORMAT CSV, HEADER TRUE)") }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_132047__expenditure') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='budget' and p.phase_id='approved'
