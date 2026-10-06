{{ config(materialized='table') }}
select dataset_id, fiscal_line_id, 'kan_change_line'::varchar as observation_role,
       amount_kind,
       source_row_id, fund_code, jurisdiction_code, fiscal_year, account_id, amendment_number,
       direction, classification, section_index, section_variant,
       kan_code, kan_name, amount_change, budget_before, budget_after, unit,
       physical_page, bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, raw_line,
       original_url, original_sha256, source_table_id, source_row_ordinal,
       additive_scope, canonical_comparable
from {{ ref('int_132071__supplementary_fy2025_01') }}
order by section_variant, cast(kan_code as integer)
