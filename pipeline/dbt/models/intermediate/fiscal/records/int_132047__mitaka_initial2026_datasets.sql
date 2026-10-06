{{ config(materialized='ephemeral') }}
with declarations as (
 select * from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json')
 where dataset_id='132047:2026:observation:budget:226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af:initial-observation'
), guard as (
 select case when count(*)=1 and bool_and(coalesce(json_extract_string(source_json,'$.provider')='mitaka-initial2026' and
  json_extract_string(source_json,'$.sourceKey')='132047-initial-2026-book-226190ff2413' and
  json_extract_string(source_json,'$.originalSourceTableId')='initial-observation' and
  json_extract_string(source_json,'$.tableId')='initial-observation' and
  json_extract_string(source_json,'$.sha256')='226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af' and
  json_extract_string(source_json,'$.rawTableSha256')='cddbb9966996b3de873c6a461bc88981e413cd2e18314433f172bb44d5d2eea2' and
  json_extract_string(source_json,'$.rawTableBytes')='386402' and
  json_extract_string(source_json,'$.phases')='[]' and
  json_type(source_json,'$.phase')='NULL' and
  json_type(source_json,'$.sourceAmountKind')='NULL' and
  json_type(source_json,'$.sourceAmountUnit')='NULL' and
  json_extract_string(source_json,'$.approvalStatus')='unconfirmed' and
  json_type(source_json,'$.approvalDate')='NULL' and
  json_type(source_json,'$.approvalProof')='NULL' and
  json_extract_string(source_json,'$.recognitionStatus')='unconfirmed' and
  json_extract_string(source_json,'$.legalCorrespondenceStatus')='unconfirmed' and
  json_extract_string(source_json,'$.cellYearRoleLinkage')='unconfirmed' and
  json_extract_string(source_json,'$.additiveWithinOwnGrain')='false' and
  json_extract_string(source_json,'$.nonadditive')='true' and
  json_extract_string(source_json,'$.canonicalInitial')='false' and
  json_extract_string(source_json,'$.canonicalChanges')='false' and
  json_extract_string(source_json,'$.canonicalExecuted')='false' and
  jurisdiction_code='132047' and
  fiscal_year=2026 and
  document_kind='budget' and
  origin_sha256='226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af' and
  direction is null and
  phases_json='[]' and
  line_count=1495,false))
 then true else error('Mitaka declaration exact-one/source-key/NULL phase/approval guard') end AS guard_ok from declarations
), actual_rows as (select count(*) n, count(*) filter(where phase is not null) bad from {{ ref('int_mitaka_initial2026') }})
select '132047:2026:observation:budget:226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af:initial-observation'::varchar dataset_id, '132047'::varchar jurisdiction_code, 2026::integer fiscal_year,
 null::varchar direction, 'budget'::varchar document_kind, '226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af'::varchar origin_sha256,
 '[]'::varchar phases_json, d.source_json::varchar source_json,
 json_extract(d.source_json,'$.structure')::varchar structure_json,
 case when a.n=1495 and a.bad=0 then a.n else error('Mitaka actual raw count/phase guard') end::bigint line_count
from guard g left join declarations d on true cross join actual_rows a where g.guard_ok
