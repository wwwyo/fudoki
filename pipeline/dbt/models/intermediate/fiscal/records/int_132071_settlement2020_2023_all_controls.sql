-- Whole-book 合計 control rows: nonadditive original references at account scope _all.
-- Never assigned to general, never joined to financial money.
select s.*,
       amount_executed as reference_amount_yen,
       'JPY' as currency,
       null::varchar as canonical_phase,
       null::bigint as canonical_financial_amount,
       'unconfirmed' as project_setsu_linkage,
       '_all' as account_scope,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__settlement2020_2023_controls') }} s
where s.account_id='_all'
