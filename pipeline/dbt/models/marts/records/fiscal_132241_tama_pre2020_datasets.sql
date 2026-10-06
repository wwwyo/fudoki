{{ config(materialized='table') }}
select * from {{ ref('int_132241__tama_pre2020_datasets') }}
