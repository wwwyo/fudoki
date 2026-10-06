{{ fiscal_csv('131016', 'r7-native-pages') }}
select * from {{ ref('stg_native__pages') }}
