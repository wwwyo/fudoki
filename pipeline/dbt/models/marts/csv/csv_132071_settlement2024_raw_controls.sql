{{ fiscal_csv('132071', 'settlement2024_raw_controls') }}
select * from {{ ref('stg_132071__settlement2024_controls') }}
