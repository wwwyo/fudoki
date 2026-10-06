-- Original control/lexical/word/page/health values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_pre2020_csv_lexical_b932d220b3f122e437c3b82e') }} s
