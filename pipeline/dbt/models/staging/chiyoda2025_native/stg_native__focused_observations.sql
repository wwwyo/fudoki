-- focused_observations: 1行=固定原典観測1行。金額・段階の拡張なし。dataset_id/source_json は宣言(join)から。
select r.*, d.dataset_id, cast(d.source_json as varchar) as declaration_source_json
from {{ source('raw_131016_r7_native_obs','focused_observations') }} r
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.tableId')='native-focused_observations'
 and json_extract_string(d.source_json,'$.provider')='chiyoda2025-native'
 and json_extract_string(d.source_json,'$.sha256')='d8783bb65906f6780918a03286b6f0375c06562a8528f10784e682123a2f8235'
