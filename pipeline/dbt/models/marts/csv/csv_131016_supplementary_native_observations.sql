{{ fiscal_csv('131016', 'supplementary_native_observations') }}
select * from {{ ref('fiscal_131016_supplementary_native_observations') }}
