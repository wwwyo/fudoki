{{ config(materialized='table') }}
select c.* from {{ ref('int_fiscal_line_dimensions') }} c join {{ ref('fiscal_settlement_expenditure_lines') }} l using(fiscal_line_id) order by fiscal_line_id,dimension
