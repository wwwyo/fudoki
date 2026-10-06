{{ fiscal_csv('131016', 'r7-native-account-controls') }}
select * from {{ ref('int_native__account_controls') }}
