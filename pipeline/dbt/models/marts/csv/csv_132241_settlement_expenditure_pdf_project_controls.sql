{{ fiscal_csv('132241', 'settlement_expenditure_pdf_project_controls') }}
select * from {{ ref('fiscal_132241_settlement_pdf_project_controls') }}
