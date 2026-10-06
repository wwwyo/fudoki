{{ fiscal_csv('131016', 'r3-native-datasets') }}
select * from {{ ref('int_native_settle__datasets') }}
