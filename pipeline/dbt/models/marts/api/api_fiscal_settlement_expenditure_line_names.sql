{{ api_model('fiscal_settlement_expenditure_line_names') }}
select c.* from {{ ref('int_fiscal_names') }} c join {{ ref('api_fiscal_settlement_expenditure_lines') }} l using(fiscal_line_id) order by fiscal_line_id,name_kind,level
