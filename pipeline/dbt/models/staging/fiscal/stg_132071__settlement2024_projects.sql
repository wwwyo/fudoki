-- One original observation per row; full original columns preserved 1:1.
select r.* exclude(_partition_table_id), d.dataset_id,
       d.dataset_id || ':' || r.source_row_ordinal as fiscal_line_id,
       'settlement' as document_kind, 'projects' as source_role,
       r._partition_table_id as original_table_id, cast(d.source_json as varchar) as source_json
from {{ source('raw_132071_settlement2024', 'projects') }} r
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.sha256')=r.original_sha256
 and json_extract_string(d.source_json,'$.tableId')=r._partition_table_id
 and json_extract_string(d.source_json,'$.provider')='akishima-settlement2024'
