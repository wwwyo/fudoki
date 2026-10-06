{{ fiscal_csv('132195', 'initial_detail_recovered') }}
select * from {{ ref('fiscal_132195_initial_detail_recovered_lines') }}
