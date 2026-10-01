{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/131016/settlement_expenditure.csv' (FORMAT CSV, HEADER TRUE)") }}
select p.* exclude(phase_id,value,source_amount),p.value as amount from {{ ref('pkg_131016__expenditure') }} p join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.document_kind='settlement' and p.phase_id='executed'
