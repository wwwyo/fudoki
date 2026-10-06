select *, 'additive: account expenditure total component (moku grain)' as grain_additivity
from {{ ref('stg_native__moku_controls') }} where role='moku-control'
union all
select *, 'nonadditive: printed page subtotal row'
from {{ ref('stg_native__moku_controls') }} where role<>'moku-control'
union all
select *, 'nonadditive: independent legal-setsu grain'
from {{ ref('stg_native__legal_amounts') }}
union all
select *, 'nonadditive: independent project/explanation grain'
from {{ ref('stg_native__explanation_amounts') }}
