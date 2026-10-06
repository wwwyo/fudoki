{{ config(materialized='table') }}
-- Independent original grain; this model never adds other roles.
select * from {{ ref('int_132241__tama_pre2020_csv_lexical_5913afed4e963fe5cc24d97a') }}
