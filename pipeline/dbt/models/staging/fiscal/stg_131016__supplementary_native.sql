with identified as (
select r.*,
       '131016:' || _partition_fiscal_year || ':expenditure:supplementary:' || _partition_origin_sha256 || ':' || _partition_table_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id
from {{ source('raw_131016_supplementary_native', 'rows') }} r
)
select s.*, d.source_json
from identified s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d using (dataset_id)
where json_extract_string(d.source_json, '$.namespace') = 'chiyoda-supplementary-native'
