{{ fiscal_csv('132195', 'supplementary_moku_reference_observations') }}
select * from {{ ref('fiscal_supplementary_moku_reference_observations') }}
