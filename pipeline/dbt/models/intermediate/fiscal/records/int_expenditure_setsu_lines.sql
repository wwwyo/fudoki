{{ fiscal_expenditure_setsu_lines('budget', 'approved') }}

union all
select h.fiscal_line_id, h.dataset_id, h.source_row, h.fund_code, h.fund_label,
       h.jurisdiction_code, h.fiscal_year, h.initial_yen as amount,
       null::varchar as cofog_code, 'unclassified' as cofog_status,
       '目単位の初回収録。分類・節への対応は未確認' as cofog_basis,
       'retained' as consolidation, '' as counterpart_fund,
       h.fiscal_line_id as group_path_key, 3 as setsu_ordinal, false as setsu_present,
       null::varchar as expenditure_setsu_id, null::varchar as setsu_label, '[]' as sub_path_json
from {{ ref('int_fiscal_budget_history') }} h where h.record_kind='initial'
