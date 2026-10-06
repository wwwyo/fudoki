{{ fiscal_csv('132071', 'settlement2024_raw_page_inventory') }}
select * from {{ ref('stg_132071__settlement2024_page_inventory') }}
