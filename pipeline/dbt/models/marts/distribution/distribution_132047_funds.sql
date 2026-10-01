{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132047/funds.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('pkg_132047__funds') }}
