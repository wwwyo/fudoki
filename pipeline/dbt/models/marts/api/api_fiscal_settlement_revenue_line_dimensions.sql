{{ api_model('fiscal_settlement_revenue_line_dimensions') }}
select c.* from {{ ref('int_fiscal_line_dimensions') }} c join {{ ref('api_fiscal_settlement_revenue_lines') }} l using(fiscal_line_id) order by fiscal_line_id,dimension
