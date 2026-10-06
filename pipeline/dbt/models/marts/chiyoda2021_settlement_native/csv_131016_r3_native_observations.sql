{{ fiscal_csv('131016', 'r3-native-observations') }}
select * from {{ ref('stg_native_settle__observations') }}
