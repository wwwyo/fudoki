{{ fiscal_csv('132071', 'settlement2019_page_inventory') }}
select * from {{ ref('fiscal_132071_settlement2019_page_inventory') }}
