-- setsu: 1行=固定原典観測1行。金額・段階の拡張なし。dataset_id/source_json は宣言(join)から。
select r.*, d.dataset_id, cast(d.source_json as varchar) as declaration_source_json
from {{ source('raw_131016_r3_native','setsu') }} r
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.tableId')='native-setsu'
 and json_extract_string(d.source_json,'$.provider')='chiyoda2021-settlement-native'
 and json_extract_string(d.source_json,'$.sha256')='8477b068a4d5a998da2614391a1e932fa7d1d5d1693cbcfed3723cb7e6f9dc6e'
