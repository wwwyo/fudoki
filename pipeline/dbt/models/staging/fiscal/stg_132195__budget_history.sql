select cast(jurisdiction as varchar) as jurisdiction_code, cast(year as integer) as fiscal_year,
       direction, document_kind, edition as origin_sha256, resource as table_id,
       jurisdiction_code || ':' || fiscal_year || ':' || direction || ':' || document_kind || ':' || edition || ':' || resource as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id,
       source_row, record_kind, fund_code, fund_label, kan_code, kou_code, moku_code, moku_label,
       initial_text, before_text, delta_text, after_text, reported_amount_text, executed_amount_text,
       cast(replace(initial_text, ',', '') as bigint) as initial_amount,
       cast(replace(before_text, ',', '') as bigint) as before_amount,
       cast(replace(replace(delta_text, ',', ''), '△', '-') as bigint) as delta_amount,
       cast(replace(after_text, ',', '') as bigint) as after_amount,
       page_number, bbox_json, printed_text
       , cast(replace(reported_amount_text, ',', '') as bigint) as reported_amount
       , cast(replace(executed_amount_text, ',', '') as bigint) as executed_amount
from {{ source('raw_132195_history', 'data') }}
