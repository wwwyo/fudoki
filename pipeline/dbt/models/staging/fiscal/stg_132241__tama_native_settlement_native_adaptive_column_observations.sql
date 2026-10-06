-- Exactly one output row per fixed original observation; no phase or monetary expansion.
select r.* exclude(_partition_table_id), cast(null as varchar) as direction,
       cast(r.financial_year as integer) as fiscal_year, d.dataset_id,
       d.dataset_id || ':' || r.observed_id as fiscal_line_id,
       'settlement' as document_kind, 'native-adaptive-column-observations' as source_role,
       r._partition_table_id as original_table_id, cast(d.source_json as varchar) as source_json
from {{ source('raw_132241_tama_native_settlement', 'native_adaptive_column_observations') }} r
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.sha256')=r.origin_sha256
 and json_extract_string(d.source_json,'$.tableId')=r._partition_table_id
 and json_extract_string(d.source_json,'$.provider')='tama-native-settlement'
