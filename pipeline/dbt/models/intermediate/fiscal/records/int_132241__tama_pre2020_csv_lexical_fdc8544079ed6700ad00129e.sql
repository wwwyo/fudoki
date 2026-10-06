-- Original control/lexical/word/page/health values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_pre2020_csv_lexical_fdc8544079ed6700ad00129e') }} s
