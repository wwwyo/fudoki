-- Independent printed observations: canonical phase and financial amount stay NULL.
-- Excludes the four whole-account 合計 rows (dedicated int_..._all_controls).
select s.*,
       amount_executed as reference_amount_yen,
       'JPY' as currency,
       null::varchar as canonical_phase,
       null::bigint as canonical_financial_amount,
       'unconfirmed' as project_setsu_linkage,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__settlement2020_2023_controls') }} s
where s.account_id<>'_all'
