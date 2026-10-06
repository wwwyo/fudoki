-- Exactly one output row per fixed original observation; no phase or monetary expansion.
select r.* exclude(_partition_table_id),
       cast(json_extract(d.source_json,'$.fiscalYear') as integer) as fiscal_year,
       '132241' as jurisdiction_code,
       d.dataset_id,
       d.dataset_id || ':' || cast(r.source_ordinal as varchar) as fiscal_line_id,
       json_extract_string(d.source_json,'$.documentKind') as document_kind,
       'project-expenditure-original-rows' as source_role,
       r._partition_table_id as original_table_id, cast(d.source_json as varchar) as source_json
from {{ source('raw_132241_tama_ordinary_history', 'project_rows') }} r
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.sha256')=r.origin_sha256
 and json_extract_string(d.source_json,'$.tableId')=r._partition_table_id
 and json_extract_string(d.source_json,'$.provider')='tama-ordinary-history'
