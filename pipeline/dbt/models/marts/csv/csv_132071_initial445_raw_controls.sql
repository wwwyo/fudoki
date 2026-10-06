{{ fiscal_csv('132071', 'initial445_raw_controls') }}
select * from {{ ref('stg_132071__initial445_controls') }}
