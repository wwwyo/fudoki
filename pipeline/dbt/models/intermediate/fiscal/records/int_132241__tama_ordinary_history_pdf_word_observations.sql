-- Original observations remain separate, nonadditive rows; no fiscal amount expansion.
select s.*
from {{ ref('stg_132241__tama_ordinary_history_pdf_word_observations') }} s
