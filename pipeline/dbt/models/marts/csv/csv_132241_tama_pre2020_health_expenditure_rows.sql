{{ fiscal_csv('132241', 'tama_pre2020_health_expenditure_rows') }}
select * from {{ ref('fiscal_132241_tama_pre2020_health_expenditure_rows') }}
