{{ config(materialized='table') }}
select s.*, true as nonadditive
from {{ ref('stg_132241__supplementary_native') }} s
where ends_with(table_id, '-observations')
order by dataset_id, source_row
