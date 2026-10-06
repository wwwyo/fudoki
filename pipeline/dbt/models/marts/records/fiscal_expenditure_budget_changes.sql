{{ config(materialized='table') }}
select 'c-' || sha256(h.fiscal_line_id) as change_id, h.dataset_id, h.budget_item_id,
       h.delta_yen as amount_delta, 'supplementary' as change_kind, h.effective_at,
       h.amendment_number::bigint as sequence, h.source_row,
       null::varchar as counterpart_budget_item_id, null::bigint as carryover_from_year, null::bigint as carryover_to_year,
       null::varchar as cofog_code, 'unclassified' as cofog_status,
       '目単位の初回収録。分類・節への対応は未確認' as cofog_basis,
       cast(to_json([struct_pack(path := []::json[], amount := h.delta_yen, fiscalLineId := h.fiscal_line_id, sourceRow := h.source_row)]) as varchar) as details_json
from {{ ref('int_fiscal_budget_history') }} h where h.record_kind='change'
  and not exists (
    select 1 from {{ ref('int_supplementary_expenditure_changes') }} d
    where d.jurisdiction_code=h.jurisdiction_code and d.fiscal_year=h.fiscal_year
      and d.fund_label=h.fund_label and d.amendment_number=h.amendment_number
  )
union all
select 'c-' || sha256(h.fiscal_line_id) as change_id,h.dataset_id,h.budget_item_id,
       h.delta_yen as amount_delta,'supplementary' as change_kind,h.effective_at,
       h.amendment_number::bigint as sequence,h.source_row,
       null::varchar as counterpart_budget_item_id,null::bigint as carryover_from_year,null::bigint as carryover_to_year,
       null::varchar as cofog_code,'unclassified' as cofog_status,
       '原典の事業×節を保持。法定節の確認とCOFOGの判断は別で、COFOGは未分類' as cofog_basis,
       '[' || json_object('path',h.account_path_json::json,'amount',h.delta_yen,
         'fiscalLineId',h.fiscal_line_id,'sourceRow',h.source_row,
         'dimensions',h.dimensions_json::json,'observedSourceGrain',h.source_grain,
         'expenditureSetsuId',h.expenditure_setsu_id,'expenditureSetsuStatus',h.expenditure_setsu_status,
         'printedSetsuCode',h.setsu_code,'printedSetsuLabel',h.setsu_label,
         'printedDepartment',h.department_text,'projectSourceRow',h.project_source_row,
         'printedProjectDelta',h.project_printed_delta,'projectEvidence',h.project_evidence_json::json,
         'originalMokuControl',h.control_moku_json::json,'printedValue',h.printed_amount_text,
         'sourceAmountUnit',h.source_amount_unit,'page',h.page_number,'bbox',h.bbox_json::json,
         'sourceLocations',h.source_locations_json::json,'printedText',h.printed_text,
         'leftSetsuEvidence',h.left_setsu_evidence_json::json,'unitEvidence',h.unit_evidence_json::json,
         'approvalDate',h.approval_date,'approvalEvidence',h.approval_evidence_json::json,
         'observedGrainValidationStatus',h.observed_grain_validation_status,
         'setsuCorrespondenceStatus',h.setsu_correspondence_status) || ']' as details_json
from {{ ref('int_supplementary_expenditure_changes') }} h
union all
select * from {{ ref('fiscal_132195_council_expenditure_budget_changes') }}
union all
select * from {{ ref('fiscal_132195_native_council_expenditure_budget_changes') }}
union all
select * from {{ ref('fiscal_132195_held5_council_expenditure_budget_changes') }}
order by change_id
