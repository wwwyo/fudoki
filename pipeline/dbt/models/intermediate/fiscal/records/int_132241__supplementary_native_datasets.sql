select d.dataset_id, d.jurisdiction_code, d.fiscal_year, d.direction, d.document_kind,
       json_extract_string(d.source_json, '$.sha256') as origin_sha256,
       case when json_extract_string(d.source_json, '$.composedCanonicalChanges') = 'true' then '[]'
            when json_extract_string(d.source_json, '$.canonicalChanges') = 'true'
                  and json_extract_string(d.source_json, '$.observationRole') = 'expenditure'
            then '["adjusted"]' else '[]' end as phases_json,
       d.source_json, json_extract(d.source_json, '$.structure')::varchar as structure_json,
       json_extract(d.source_json, '$.rawRowCount')::bigint as line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
where json_extract_string(d.source_json, '$.namespace') = 'tama-supplementary-native'
