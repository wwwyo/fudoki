-- 5 raw datasets の registry。int_fiscal_datasets の共有契約列に揃える。
with obs as (
select 'native-pages' as table_id, count(*) as line_count from {{ ref('stg_native_settle__pages') }}
union all select 'native-observations', count(*) from {{ ref('stg_native_settle__observations') }}
union all select 'native-levels', count(*) from {{ ref('stg_native_settle__levels') }}
union all select 'native-setsu', count(*) from {{ ref('stg_native_settle__setsu') }}
union all select 'native-notes', count(*) from {{ ref('stg_native_settle__notes') }}
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
 and json_extract_string(d.source_json,'$.provider')='chiyoda2021-settlement-native'
 and json_extract_string(d.source_json,'$.sha256')='8477b068a4d5a998da2614391a1e932fa7d1d5d1693cbcfed3723cb7e6f9dc6e'
