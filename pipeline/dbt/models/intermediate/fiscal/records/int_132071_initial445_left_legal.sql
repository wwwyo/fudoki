select s.*, amount * 1000::bigint as reference_amount_yen,
       m.expenditure_setsu_id as independently_validated_statutory_setsu_id,
       case when m.expenditure_setsu_id is not null then 'confirmed-printed-code-name-active-year'
            else 'unconfirmed-printed-name-master-conflict' end as independent_master_status,
       null::varchar as canonical_phase, null::bigint as canonical_financial_amount,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__initial445_left_legal') }} s
left join {{ ref('fiscal_expenditure_setsu_master') }} m
 on try_cast(m.code as integer)=try_cast(s.printed_code as integer)
 and m.label=s.printed_name_confirmed
 and s.fiscal_year>=coalesce(m.valid_from_fiscal_year,-9999)
 and s.fiscal_year<=coalesce(m.valid_to_fiscal_year,9999)
