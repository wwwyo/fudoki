{{ config(materialized='table') }}
-- Independent original grain; this model never adds other roles.
select * from {{ ref('int_132241__tama_pre2020_csv_lexical_d6e7457d708162add52d382f') }}
