select r.*,
       '132241:' || _partition_fiscal_year || ':expenditure:supplementary:' ||
       _partition_origin_sha256 || ':' || table_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id
from {{ source('raw_132241_supplementary_native', 'rows') }} r
