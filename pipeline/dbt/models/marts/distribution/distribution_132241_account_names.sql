{{ fiscal_distribution_csv('132241', 'account_names') }}
select * from {{ ref('pkg_132241__account_names') }}
