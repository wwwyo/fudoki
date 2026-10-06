{{ fiscal_csv('132071', 'settlement2020_2023_raw_financial') }}
select * from {{ ref('stg_132071__settlement2020_2023_financial') }}
