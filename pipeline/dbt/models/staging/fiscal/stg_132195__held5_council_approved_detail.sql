select *, 'expenditure'::varchar as direction, 'supplementary'::varchar as document_kind,
       'supplementary-expenditure-project-setsu-held5-council-original-'
          || case when fund_label='一般会計' then 'general' when fund_label='介護保険特別会計' then 'care' when fund_label='国民健康保険特別会計' then 'health' when fund_label='後期高齢者医療特別会計' then 'late' when fund_label='駐車場事業特別会計' then 'parking' end
          || '-' || amendment_number as table_id,
       jurisdiction_code || ':' || fiscal_year || ':expenditure:supplementary:' || origin_sha256
          || ':' || table_id as dataset_id,
       dataset_id || ':' || source_row as fiscal_line_id,
       null::varchar as fund_code
from {{ source('raw_132195_held5_council_approved_detail','data') }}
