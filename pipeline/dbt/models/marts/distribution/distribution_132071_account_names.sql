{{ fiscal_distribution_csv('132071', 'account_names') }}
select * from {{ ref('pkg_132071__account_names') }}
