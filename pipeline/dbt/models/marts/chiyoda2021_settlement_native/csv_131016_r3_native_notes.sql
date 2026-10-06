{{ fiscal_csv('131016', 'r3-native-notes') }}
select * from {{ ref('stg_native_settle__notes') }}
