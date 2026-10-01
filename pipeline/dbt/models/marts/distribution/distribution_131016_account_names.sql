{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/131016/account_names.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('pkg_131016__account_names') }}
