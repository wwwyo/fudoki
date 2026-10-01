{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132071/account_names.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('pkg_132071__account_names') }}
