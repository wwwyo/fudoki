{{ fiscal_distribution_csv('132047', 'account_names') }}
select * from {{ ref('pkg_132047__account_names') }}
