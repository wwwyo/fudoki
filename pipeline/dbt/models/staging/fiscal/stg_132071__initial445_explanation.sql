select r.*, 'budget'::varchar as document_kind,
       '132071:' || fiscal_year || ':expenditure:budget:' || origin_sha256 || ':' || resource_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id
from {{ source('raw_132071_initial445', 'explanation') }} r
