{{ fiscal_csv('131016', 'r7-native-legal-amounts') }}
select * from {{ ref('stg_native__legal_amounts') }}
