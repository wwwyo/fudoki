{{ config(materialized='table') }}
-- Independent original grain; this model never adds other roles.
select * from {{ ref('int_132241__tama_pre2020_csv_lexical_fdc8544079ed6700ad00129e') }}
