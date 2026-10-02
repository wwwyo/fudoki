{{ fiscal_distribution_csv('132071', 'funds') }}
select * from {{ ref('pkg_132071__funds') }}
