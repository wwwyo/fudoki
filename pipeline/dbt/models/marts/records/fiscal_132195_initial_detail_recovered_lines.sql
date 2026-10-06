{{ config(materialized='table', tags=['komae-recovered']) }}
-- Full-fidelity mart: every record kind, every printed column, phase NULL.
select fiscal_line_id, dataset_id, jurisdiction_code, fiscal_year, direction,
       phase, approval_status, additive, nonadditive_reason,
       record_kind, kan_code, kan_label, kou_code, kou_label,
       printed_kan_total, printed_kou_total,
       moku_code, moku_label, setsu_no, setsu_label, setsu_text, setsu_amount,
       parent_moku_code, parent_moku_label, parent_moku_source_row, parent_evidence,
       description, current_text, current_amount, prior_text, prior_amount,
       change_text, change_amount, natl_text, natl_amount, metro_text, metro_amount,
       bond_text, bond_amount, other_src_text, other_src_amount, general_text, general_amount,
       physical_page, page_number, y, bbox_json, printed_text, source_row,
       source_amount_unit, source_url, source_sha256, wayback_url, wayback_capture
from {{ ref('int_132195_initial_detail_recovered') }}
order by dataset_id, source_row
