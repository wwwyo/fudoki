{{ fiscal_csv('132071', 'settlement2019_raw_financial') }}
select * from {{ ref('stg_132071__settlement2019_financial') }}
