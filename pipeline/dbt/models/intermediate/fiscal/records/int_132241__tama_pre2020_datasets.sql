-- Exactly the existing generic registry column contract, with observed role counts.
with observed as (
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_account_reference_controls') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_19bec615dee3a5b46ebd909a') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_25441b6f6231db8c1f25201f') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_46a00db04b5869e24545c5a7') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_5913afed4e963fe5cc24d97a') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_5b69ea19f017e41ec4393479') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_60fc49788be4981884a79db9') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_67cdd0c9153009df6f0e9a51') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_881094d87494b60f7735562b') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_a77f5c67b8f19ad857804fd9') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_acb2d4d787059d9ccc9dc021') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_b932d220b3f122e437c3b82e') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_cdfc82e18507c69faddb1234') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_d6e7457d708162add52d382f') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_d8f101e90000421349f9d0f5') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_ec19115add00785366b1ed98') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_csv_lexical_fdc8544079ed6700ad00129e') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_health_expenditure_rows') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_pdf_page_observations') }} group by dataset_id
union all
select dataset_id, cast(max(jurisdiction_code) as varchar) as jurisdiction_code,
       cast(json_extract(max(source_json),'$.fiscalYear') as integer) as fiscal_year,
       cast(json_extract_string(max(source_json),'$.direction') as varchar) as direction,
       cast(max(document_kind) as varchar) as document_kind,
       cast(max(origin_sha256) as varchar) as origin_sha256,
       cast(max(source_json) as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_pre2020_pdf_word_observations') }} group by dataset_id
)
select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,
       cast(json_extract(source_json,'$.phases') as varchar) as phases_json,
       source_json, cast(json_extract(source_json,'$.structure') as varchar) as structure_json,
       cast(line_count as bigint) as line_count
from observed
