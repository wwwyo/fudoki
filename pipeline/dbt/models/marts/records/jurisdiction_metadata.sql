{{ config(materialized='table') }}
select * from {{ ref('int_fiscal_jurisdiction_metadata') }} order by jurisdiction_code
