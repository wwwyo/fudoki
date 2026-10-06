{{ fiscal_csv('132071', 'initial445_raw_left_legal') }}
select * from {{ ref('stg_132071__initial445_left_legal') }}
