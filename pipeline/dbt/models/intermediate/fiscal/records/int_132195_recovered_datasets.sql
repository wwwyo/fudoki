{{ config(tags=['komae-recovered']) }}
-- Generic-union arm: register the 8 recovered datasets with phases=[]
-- (chapter documents carry no printed phase boundary), non-additive.
select h.dataset_id, h.jurisdiction_code, cast(h.fiscal_year as integer) as fiscal_year,
       h.direction, h.document_kind, h.origin_sha256,
       '[]'::varchar as phases_json,
       h.source_json, h.structure_json, h.line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h
where json_extract_string(h.source_json, '$.provider') = 'ingestion.fiscal.jurisdictions.132195.layouts.komae_recovered_provider'
