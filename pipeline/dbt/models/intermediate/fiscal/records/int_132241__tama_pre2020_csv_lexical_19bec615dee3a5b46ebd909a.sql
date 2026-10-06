-- Original control/lexical/word/page/health values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_pre2020_csv_lexical_19bec615dee3a5b46ebd909a') }} s
