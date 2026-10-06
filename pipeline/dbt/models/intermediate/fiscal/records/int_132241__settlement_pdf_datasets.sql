{{ config(materialized='table') }}
-- Registry for this isolated source branch. Controls and words are not fiscal leaves.
with observations as (
{% for role in ['legal_setsu','project_funding','moku_controls','account_controls','project_controls','source_words'] %}
select dataset_id, jurisdiction_code, fiscal_year, direction, document_kind, origin_sha256,
       table_id, grain, observation_role, fund_label, cast(source_amount_unit as varchar) as source_amount_unit, cast(unit_multiplier as bigint) as unit_multiplier,
       additive_within_own_grain, cast(source_json as varchar) as source_json
from {{ ref('int_132241__settlement_pdf_' ~ role) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
)
select dataset_id, jurisdiction_code, fiscal_year, direction, document_kind, origin_sha256,
       table_id, grain, observation_role, fund_label, source_amount_unit, unit_multiplier,
       additive_within_own_grain, source_json, count(*) as observation_count
from observations group by all
