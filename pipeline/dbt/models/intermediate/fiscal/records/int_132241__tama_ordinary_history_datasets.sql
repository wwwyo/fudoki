-- Exactly the existing generic registry column contract, with observed role counts.
with observed as (
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_ordinary_history_pdf_word_observations') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_ordinary_history_pdf_page_observations') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_ordinary_history_project_rows') }} group by dataset_id
)select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,
       cast(json_extract(source_json,'$.phases') as varchar) as phases_json,
       source_json, cast(json_extract(source_json,'$.structure') as varchar) as structure_json,
       cast(line_count as bigint) as line_count
from observed
