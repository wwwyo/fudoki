{{ fiscal_csv('132241', 'initial_native_observations') }}
select * from {{ ref('fiscal_132241_initial_native_observations') }}
