{{ fiscal_csv('132241', 'tama_ordinary_history_datasets') }}
select * from {{ ref('fiscal_132241_tama_ordinary_history_datasets') }}
