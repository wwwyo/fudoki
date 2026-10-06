{{ fiscal_csv('132071', 'settlement2019_revenue_observations') }}
select * from {{ ref('fiscal_132071_settlement2019_revenue_observations') }}
