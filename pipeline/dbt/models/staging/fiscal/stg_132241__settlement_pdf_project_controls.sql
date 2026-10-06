-- One original observation per row. Table ID separates independent breakdowns and controls.
select r.*,
       jurisdiction_code || ':' || fiscal_year || ':expenditure:settlement:' || origin_sha256 || ':' || table_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id
from {{ source('raw_132241_settlement_pdf', 'project_controls') }} r
