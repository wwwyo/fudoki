{{ fiscal_csv('132241', 'tama_settlement_pdf_datasets') }}
select * from {{ ref('fiscal_132241_settlement_pdf_datasets') }}
