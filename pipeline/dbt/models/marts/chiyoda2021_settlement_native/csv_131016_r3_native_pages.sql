{{ fiscal_csv('131016', 'r3-native-pages') }}
select * from {{ ref('stg_native_settle__pages') }}
