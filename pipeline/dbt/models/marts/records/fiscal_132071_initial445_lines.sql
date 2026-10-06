{{ config(materialized='table') }}
select fiscal_line_id,dataset_id,budget_item_id,source_row,initial_yen as amount,
       '[' || json_object('path',account_path_json::json,'amount',initial_yen,
          'fiscalLineId',fiscal_line_id,'sourceRow',source_row,
          'originalSourceRowIdentity',source_row_id,'rawOriginal',original_raw_and_staging_json::json,
          'observedSourceGrain',source_grain,'printedSetsuCode',printed_setsu_code,
          'statutorySetsuId',statutory_setsu_id,'statutoryCorrespondence','unconfirmed-no-printed-explanation-code',
          'sourceAmountUnit',amount_unit,'printedValue',printed_value,
          'originalPhysicalPage',physical_page,'bbox',source_bbox::json,
          'targetIdentity',target_identity_json::json,'otherTargetCorrespondence',target_correspondence_status) || ']' as details_json,
       null::varchar as consolidation,null::varchar as counterpart_fund,
       null::varchar as cofog_code,'unclassified'::varchar as cofog_status,
       '印刷された説明欄の行・事業経路を保持。法定節コードの対応およびCOFOG分類は未確認'::varchar as cofog_basis
from {{ ref('int_132071_initial445') }}
order by fiscal_line_id
