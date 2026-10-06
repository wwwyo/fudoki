-- nonadditive union: the three printed tables are alternative classifications of the same
-- amendment money. additive_scope marks the only safe summation boundary (one table).
select *, 'fy2025-supp01'::varchar as document_tag from {{ ref('stg_132071__supplementary_fy2025_01_revenue') }}
union all
select *, 'fy2025-supp01' from {{ ref('stg_132071__supplementary_fy2025_01_expenditure_purpose') }}
union all
select *, 'fy2025-supp01' from {{ ref('stg_132071__supplementary_fy2025_01_expenditure_nature') }}
