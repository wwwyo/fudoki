{{ fiscal_csv('132241', 'tama_native_settlement_nonfinancial_and_other_native_observations') }}
select * from {{ ref('fiscal_132241_tama_native_settlement_nonfinancial_and_other_native_observations') }}
