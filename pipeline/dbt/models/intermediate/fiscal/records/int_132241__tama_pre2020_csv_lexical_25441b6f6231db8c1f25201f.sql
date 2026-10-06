-- Original control/lexical/word/page/health values remain separate, nonadditive observations.
select s.*
from {{ ref('stg_132241__tama_pre2020_csv_lexical_25441b6f6231db8c1f25201f') }} s
