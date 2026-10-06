{{ fiscal_csv('132071', 'settlement2019_raw_projects') }}
select * from {{ ref('stg_132071__settlement2019_projects') }}
