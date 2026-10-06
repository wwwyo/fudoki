{{ fiscal_csv('132071', 'settlement2019_raw_page_inventory') }}
select * from {{ ref('stg_132071__settlement2019_page_inventory') }}
