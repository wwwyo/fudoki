{{ config(materialized='table') }}
select * from {{ ref('int_132071_settlement2024_projects') }}
