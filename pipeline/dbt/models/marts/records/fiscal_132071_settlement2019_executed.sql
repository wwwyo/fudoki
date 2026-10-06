{{ config(materialized='table') }}
select fiscal_line_id, dataset_id, source_row_ordinal as source_row,
       ''::varchar as fund_code, account_name as fund_label, amount,
       account_path_json, dimensions_json,
       '[' || json_object('path',account_path_json::json,'amount',amount,
          'fiscalLineId',fiscal_line_id,'sourceRow',source_row_ordinal,
          'originalSourceRowIdentity',source_row_id,'rawOriginal',original_raw_and_staging_json::json,
          'observedSourceGrain',source_grain,'printedSetsuCode',printed_setsu_code,
          'printedSetsuName',printed_setsu_name,'mappedExpenditureSetsuId',mapped_expenditure_setsu_id,
          'legalMappingStatus',legal_mapping_status,
          'sourceAmountUnit',unit,'originalPhysicalPage',physical_page,
          'kubunAmount',kubun_amount,'bikouNo',bikou_no,
          'carryColumns',json_object('continuing',carry_next_continuing,'authorized',carry_next_authorized,'accident',carry_next_accident),
          'unspent',unspent,'printedExecutionRatio',exec_ratio,
          'recognitionBill',recognition_bill,'recognitionDate',recognition_date,
          'recognitionStatus',recognition_status) || ']' as details_json,
       null::varchar as consolidation, null::varchar as counterpart_fund,
       null::varchar as cofog_code, 'unclassified'::varchar as cofog_status,
       '款・項・目と印刷された節の行を保持。法定節対応は判断列、COFOG分類は未確認'::varchar as cofog_basis
from {{ ref('int_132071_settlement2019_executed') }}
order by fiscal_line_id
