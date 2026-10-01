{{ config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_PACKAGE_DIR') ~ "/132195/project_names.csv' (FORMAT CSV, HEADER TRUE)") }}
select * from {{ ref('pkg_132195__project_names') }}
