{{ config(materialized='table') }}
select * from {{ ref('int_initial_expenditure_moku_setsu') }}
order by dataset_id, source_row
