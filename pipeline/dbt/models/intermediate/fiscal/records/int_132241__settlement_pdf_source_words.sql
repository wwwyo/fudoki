-- Independent original grain; no allocation or joins across legal and funding breakdowns.
select s.*, d.source_json,
       s.grain as line_granularity,
       'unconfirmed' as project_setsu_linkage,
       false as additive_within_own_grain,
       'unconfirmed' as cofog_status
from {{ ref('stg_132241__settlement_pdf_source_words') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d using(dataset_id)
