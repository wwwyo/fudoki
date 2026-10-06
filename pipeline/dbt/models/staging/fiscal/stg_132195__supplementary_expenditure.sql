select *, 'expenditure'::varchar as direction, 'supplementary'::varchar as document_kind,
       'supplementary-expenditure-project-setsu'::varchar as table_id,
       jurisdiction_code || ':' || fiscal_year || ':expenditure:supplementary:' || origin_sha256
         || ':supplementary-expenditure-project-setsu' as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id,
       null::varchar as fund_code
from {{ source('raw_132195_supplementary_detail', 'data') }}
