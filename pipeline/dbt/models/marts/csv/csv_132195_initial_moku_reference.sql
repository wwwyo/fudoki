{{ fiscal_csv('132195', 'initial_moku_reference') }}
select fiscal_line_id,dataset_id,source_row,budget_item_id,amount_initial as amount,
       observation_role,superseded_by_full_initial_detail,
       to_json(r)::varchar as source_observation_json
from {{ ref('fiscal_132195_initial_moku_reference') }} r
order by fiscal_line_id
