{{ fiscal_csv('131016', 'r7-native-moku-controls') }}
select * from {{ ref('stg_native__moku_controls') }}
