{{ fiscal_distribution_csv('132195', 'project_names') }}
select * from {{ ref('pkg_132195__project_names') }}
