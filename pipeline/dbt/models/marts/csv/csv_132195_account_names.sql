{{ fiscal_csv('132195', 'account_names') }}
select * from {{ ref('pkg_132195__account_names') }}
