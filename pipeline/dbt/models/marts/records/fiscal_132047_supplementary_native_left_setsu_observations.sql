{{ config(materialized='table') }}
select s.*, true as nonadditive
from {{ ref('stg_132047__supplementary_native') }} s
where ends_with(table_id, '-left_setsu_observations')
order by dataset_id, source_row
