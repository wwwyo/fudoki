-- Independent printed 事業備考 observations; no linkage to setsu claimed.
select s.*,
       amount as reference_amount_yen,
       'JPY' as currency,
       null::varchar as canonical_phase,
       null::bigint as canonical_financial_amount,
       'unconfirmed' as project_setsu_linkage,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__settlement2019_projects') }} s
