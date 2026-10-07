select r.*, '132241:2026:expenditure:budget:a991d897f8fb97774bbf48ce3c990d7a91057b80763a5cfdc83d3265f3661c47:' || table_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id
from {{ source('raw_132241_initial_native', 'rows') }} r
