{{ fiscal_csv('131016', 'r7-native-focused-observations') }}
select * from {{ ref('stg_native__focused_observations') }}
