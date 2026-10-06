{{ config(materialized='table') }}
select * from {{ ref('int_132071_settlement2020_2023_controls') }}
