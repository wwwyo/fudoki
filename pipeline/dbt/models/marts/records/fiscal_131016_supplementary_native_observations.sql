{{ config(materialized='table') }}
select s.*, true as nonadditive
from {{ ref('stg_131016__supplementary_native') }} s
order by dataset_id, source_row
