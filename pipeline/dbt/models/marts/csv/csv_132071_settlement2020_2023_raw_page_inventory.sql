{{ fiscal_csv('132071', 'settlement2020_2023_raw_page_inventory') }}
select * from {{ ref('stg_132071__settlement2020_2023_page_inventory') }}
