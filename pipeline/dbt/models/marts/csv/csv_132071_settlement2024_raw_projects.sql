{{ fiscal_csv('132071', 'settlement2024_raw_projects') }}
select * from {{ ref('stg_132071__settlement2024_projects') }}
