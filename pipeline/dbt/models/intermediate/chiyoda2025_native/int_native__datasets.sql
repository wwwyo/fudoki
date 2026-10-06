-- 8 raw datasets の registry。int_fiscal_datasets の共有契約列に揃える。
with obs as (
select 'native-pages' as table_id, count(*) as line_count from {{ ref('stg_native__pages') }}
union all select 'native-observations', count(*) from {{ ref('stg_native__observations') }}
union all select 'native-focused_observations', count(*) from {{ ref('stg_native__focused_observations') }}
union all select 'native-financial_cells', count(*) from {{ ref('stg_native__financial_cells') }}
union all select 'native-moku_controls', count(*) from {{ ref('stg_native__moku_controls') }}
union all select 'native-legal_amounts', count(*) from {{ ref('stg_native__legal_amounts') }}
union all select 'native-explanation_amounts', count(*) from {{ ref('stg_native__explanation_amounts') }}
union all select 'native-unresolved_cells', count(*) from {{ ref('stg_native__unresolved_cells') }}
)
select d.dataset_id, cast(d.jurisdiction_code as varchar) as jurisdiction_code,
       cast(d.fiscal_year as integer) as fiscal_year, cast(d.direction as varchar) as direction,
       d.document_kind, json_extract_string(d.source_json,'$.sha256') as origin_sha256,
       cast(json_extract(d.source_json,'$.phases') as varchar) as phases_json,
       cast(d.source_json as varchar) as source_json,
       cast(json_extract(d.source_json,'$.structure') as varchar) as structure_json,
       cast(o.line_count as bigint) as line_count
from obs o join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d
  on json_extract_string(d.source_json,'$.tableId')=o.table_id
 and json_extract_string(d.source_json,'$.provider')='chiyoda2025-native'
 and json_extract_string(d.source_json,'$.sha256')='d8783bb65906f6780918a03286b6f0375c06562a8528f10784e682123a2f8235'
