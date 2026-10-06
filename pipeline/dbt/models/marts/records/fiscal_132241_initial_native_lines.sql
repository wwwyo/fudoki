{{ config(materialized='table') }}
select 'tama-' || budget_item_id as fiscal_line_id, dataset_id, budget_item_id,
       min(source_row) as source_row, sum(initial_yen)::bigint as amount,
       to_json(list(json_object('fiscalLineId',fiscal_line_id,'sourceRow',source_row,
         'sourceObservationRow',source_observation_row,'amount',initial_yen,
         'rawOriginal',raw_original_json::json,'path',account_path_json::json,
         'physicalPage',physical_page,'bbox',bbox_json::json,
         'leftSetsuCode',left_setsu_code,'leftSetsuName',left_setsu_label,
         'statutorySetsuId',expenditure_setsu_id,'targetIdentity',target_identity_json::json,
         'otherTargetCorrespondence','unconfirmed-other-namespace-correspondence') order by source_row))::varchar as details_json,
       null::varchar as consolidation, null::varchar as counterpart_fund,
       null::varchar as cofog_code, 'unclassified'::varchar as cofog_status,
       'COFOG未分類。法定節は同じ目の左節コード・名称と年度適用マスタで確認。予備費は原典行を保持。'::varchar as cofog_basis
from {{ ref('int_132241__initial_native') }}
group by dataset_id,budget_item_id
order by fiscal_line_id
