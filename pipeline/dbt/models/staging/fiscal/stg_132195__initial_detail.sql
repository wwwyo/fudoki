select *, 'expenditure'::varchar as direction, 'budget'::varchar as document_kind,
       resource_id as table_id,
       jurisdiction_code || ':' || fiscal_year || ':expenditure:budget:' || origin_sha256
         || ':' || resource_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id,
       null::varchar as fund_code
from {{ source('raw_132195_initial_detail', 'data') }}
