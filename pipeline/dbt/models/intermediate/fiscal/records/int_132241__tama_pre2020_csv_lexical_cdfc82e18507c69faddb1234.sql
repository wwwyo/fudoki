-- Original control/lexical/word/page/health values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_pre2020_csv_lexical_cdfc82e18507c69faddb1234') }} s
