{{ fiscal_csv('132071', 'settlement2020_2023_all_controls') }}
select * from {{ ref('fiscal_132071_settlement2020_2023_all_controls') }}
