-- Exactly the existing generic registry column contract, with observed role counts.
with observed as (
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_legal_observations') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_hierarchy_controls') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_native_full_page_observations') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_native_adaptive_column_observations') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_revenue_native_observations') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_nonfinancial_and_other_native_observations') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_independent_account_controls') }} group by all
union all
select dataset_id, cast(jurisdiction_code as varchar) as jurisdiction_code, fiscal_year, cast(direction as varchar) as direction, document_kind, origin_sha256, cast(source_json as varchar) as source_json, count(*) as line_count
from {{ ref('int_132241__tama_native_settlement_page_observations') }} group by all
)
select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,
       cast(json_extract(source_json,'$.phases') as varchar) as phases_json,
       source_json, cast(json_extract(source_json,'$.structure') as varchar) as structure_json,
       cast(line_count as bigint) as line_count
from observed
