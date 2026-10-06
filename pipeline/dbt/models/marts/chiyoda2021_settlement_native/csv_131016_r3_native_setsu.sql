{{ fiscal_csv('131016', 'r3-native-setsu') }}
select * from {{ ref('stg_native_settle__setsu') }}
