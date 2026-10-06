{{ fiscal_csv('132071', 'settlement_expenditure_setsu') }}
select l.*, d.fiscal_year
from {{ ref('fiscal_settlement_expenditure_setsu_lines') }} l
join {{ ref('int_fiscal_datasets') }} d using(dataset_id)
where d.jurisdiction_code = '132071'
