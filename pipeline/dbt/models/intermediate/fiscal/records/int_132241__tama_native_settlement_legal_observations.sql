-- Original control/word/page values remain separate, nonadditive observations.
select s.*,
       cast(null as varchar) as expenditure_setsu_id,
       'unconfirmed' as setsu_correspondence_status,
       'tama-fy2020-printed-legacy-code-applicability-unconfirmed' as observed_setsu_scheme,
       'unconfirmed' as project_setsu_linkage,
       'unconfirmed' as cofog_status,
       case when amount_unit='円' and amount_multiplier=1 then executed
            else error('Native settlement printed unit identity differs') end as amount,
       'JPY' as currency
from {{ ref('stg_132241__tama_native_settlement_legal_observations') }} s
