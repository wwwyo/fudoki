select d.dataset_id, d.jurisdiction_code, d.fiscal_year, d.direction, d.document_kind,
       json_extract_string(d.source_json, '$.sha256') as origin_sha256,
       json_extract(d.source_json, '$.phases')::varchar as phases_json,
       d.source_json, json_extract(d.source_json, '$.structure')::varchar as structure_json,
       json_extract(d.source_json, '$.rawRowCount')::bigint as line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
where json_extract_string(d.source_json, '$.namespace') = 'chiyoda-supplementary-native'
  and d.jurisdiction_code = '131016' and d.fiscal_year = 2026
  and d.direction = 'expenditure' and d.document_kind = 'supplementary'
