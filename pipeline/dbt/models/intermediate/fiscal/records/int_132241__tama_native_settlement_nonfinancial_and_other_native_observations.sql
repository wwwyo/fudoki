-- Original control/word/page values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_native_settlement_nonfinancial_and_other_native_observations') }} s
