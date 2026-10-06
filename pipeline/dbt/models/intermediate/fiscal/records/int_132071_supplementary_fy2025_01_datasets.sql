-- FY2025 supplementary No.1 kan-summary datasets; printed change lines are additive only
-- within their own printed section (additive_scope='section' in rows).
select d.dataset_id, d.jurisdiction_code, d.fiscal_year, d.direction, d.document_kind,
       json_extract_string(d.source_json,'$.sha256') as origin_sha256,
       '[]' as phases_json,
       d.source_json, json_extract(d.source_json,'$.structure')::varchar as structure_json,
       json_extract(d.source_json,'$.rawRowCount')::bigint as line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
where json_extract_string(d.source_json,'$.namespace')='akishima-supplementary2020-2025'
