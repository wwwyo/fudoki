{{ fiscal_csv('132071', 'settlement2019_raw_revenue') }}
select * from {{ ref('stg_132071__settlement2019_revenue') }}
