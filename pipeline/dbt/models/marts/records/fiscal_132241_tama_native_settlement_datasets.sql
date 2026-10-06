{{ config(materialized='table') }}
select * from {{ ref('int_132241__tama_native_settlement_datasets') }}
