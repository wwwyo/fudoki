{{ config(materialized='table') }}
-- Independent original grain; this model never adds other roles.
select * from {{ ref('int_132241__tama_pre2020_csv_lexical_46a00db04b5869e24545c5a7') }}
