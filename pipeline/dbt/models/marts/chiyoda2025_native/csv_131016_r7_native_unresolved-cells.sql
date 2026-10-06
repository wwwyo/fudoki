{{ fiscal_csv('131016', 'r7-native-unresolved-cells') }}
select * from {{ ref('stg_native__unresolved_cells') }}
