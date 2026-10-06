{{ fiscal_csv('131016', 'r7-native-explanation-amounts') }}
select * from {{ ref('stg_native__explanation_amounts') }}
