select *, 'supplementary'::varchar as document_kind,
       'change'::varchar as amount_kind, ''::varchar as fund_code,
       '132071'::varchar as jurisdiction_code,
       '132071' || ':' || fiscal_year || ':expenditure:supplementary:' || original_sha256 || ':kan-summary-expenditure-purpose' as dataset_id,
       dataset_id || ':' || source_row_ordinal as fiscal_line_id
from {{ source('raw_132071_supplementary_fy2025_01', 'kan_summary_expenditure_purpose') }}
