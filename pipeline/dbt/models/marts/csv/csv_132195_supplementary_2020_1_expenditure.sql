{{ config(materialized='table', post_hook="copy (select * from {{ this }} order by dataset_id,source_row) to '{{ env_var('FUDOKI_PACKAGE_DIR') }}/132195/supplementary_2020_1_expenditure.csv' (format csv,header true)") }}
select * from {{ ref('fiscal_132195_supplementary_2020_1_expenditure_lines') }}
