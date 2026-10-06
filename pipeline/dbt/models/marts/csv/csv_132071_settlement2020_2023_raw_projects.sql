{{ fiscal_csv('132071', 'settlement2020_2023_raw_projects') }}
select * from {{ ref('stg_132071__settlement2020_2023_projects') }}
