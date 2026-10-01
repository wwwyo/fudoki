{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132071/funds.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('pkg_132071__funds') }}
