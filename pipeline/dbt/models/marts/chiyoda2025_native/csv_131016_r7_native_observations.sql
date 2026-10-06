{{ fiscal_csv('131016', 'r7-native-observations') }}
select * from {{ ref('stg_native__observations') }}
