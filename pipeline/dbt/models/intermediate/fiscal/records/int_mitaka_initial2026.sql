-- Preserve all physical fields and rows; coverage rejects invalid phase/role rather than filtering rows.
select * from {{ ref('stg_mitaka_initial2026') }}
