{{ fiscal_csv('131016', 'r7-native-financial-cells') }}
select * from {{ ref('stg_native__financial_cells') }}
