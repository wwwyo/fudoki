{{ config(materialized='table') }}
-- Independent original grain; this model never adds other roles.
select * from {{ ref('int_132241__tama_ordinary_history_datasets') }}
