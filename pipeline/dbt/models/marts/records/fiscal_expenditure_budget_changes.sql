{{ config(materialized='table') }}
select 'c-' || sha256(h.fiscal_line_id) as change_id, h.dataset_id, h.budget_item_id,
       h.delta_yen as amount_delta, 'supplementary' as change_kind, h.effective_at,
       h.amendment_number::bigint as sequence, h.source_row,
       null::varchar as counterpart_budget_item_id, null::bigint as carryover_from_year, null::bigint as carryover_to_year,
       null::varchar as cofog_code, 'unclassified' as cofog_status,
       '目単位の初回収録。分類・節への対応は未確認' as cofog_basis,
       cast(to_json([struct_pack(path := []::json[], amount := h.delta_yen, fiscalLineId := h.fiscal_line_id, sourceRow := h.source_row)]) as varchar) as details_json
from {{ ref('int_fiscal_budget_history') }} h where h.record_kind='change'
order by change_id
