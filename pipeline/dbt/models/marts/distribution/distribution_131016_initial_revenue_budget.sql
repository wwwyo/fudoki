{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/131016/initial_revenue_budget.csv' (FORMAT CSV, HEADER TRUE)") }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_131016__revenue') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='budget' and p.phase_id='approved'
