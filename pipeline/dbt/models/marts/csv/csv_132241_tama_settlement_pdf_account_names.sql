{{ fiscal_csv('132241', 'tama_settlement_pdf_account_names') }}
select * from {{ ref('fiscal_132241_settlement_pdf_account_names') }}
