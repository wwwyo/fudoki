{{ api_model('jurisdiction_metadata') }}
select * from {{ ref('int_fiscal_jurisdiction_metadata') }} order by jurisdiction_code
