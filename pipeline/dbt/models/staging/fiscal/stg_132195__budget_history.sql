select cast(jurisdiction as varchar) as jurisdiction_code, cast(year as integer) as fiscal_year,
       direction, document_kind, edition as origin_sha256, resource as table_id,
       jurisdiction_code || ':' || fiscal_year || ':' || direction || ':' || document_kind || ':' || edition || ':' || resource as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id,
       source_row, record_kind, fund_code, fund_label, kan_code, kou_code, moku_code, moku_label,
       initial_text, before_text, delta_text, after_text, reported_amount_text, executed_amount_text,
       {{ staging_amount('initial_text') }} as initial_amount,
       {{ staging_amount('before_text') }} as before_amount,
       {{ staging_amount('delta_text') }} as delta_amount,
       {{ staging_amount('after_text') }} as after_amount,
       page_number, bbox_json, printed_text
       , {{ staging_amount('reported_amount_text') }} as reported_amount
       , {{ staging_amount('executed_amount_text') }} as executed_amount
from {{ source('raw_132195_history', 'data') }}
