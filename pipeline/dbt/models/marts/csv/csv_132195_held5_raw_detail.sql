{{ config(materialized='table', post_hook="copy (select * from {{ this }} order by dataset_id,source_row) to '{{ env_var('FUDOKI_PACKAGE_DIR') }}/132195/held5_raw_detail.csv' (format csv,header true)") }}
select * from {{ ref('stg_132195__held5_council_approved_detail') }}
