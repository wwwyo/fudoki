{{ config(tags=['komae-recovered']) }}
-- Dedicated non-additive recovered lines: ALL record kinds and ALL raw fields
-- (47 printed + hive metadata). phase NULL; approval unconfirmed; never
-- unioned into generic fiscal amounts.
select hive_jurisdiction as jurisdiction_code, fiscal_year, hive_direction as direction,
       hive_document_kind as document_kind, hive_edition as origin_sha256,
       hive_resource as table_id, dataset_id, fiscal_line_id,
       null::varchar as phase, 'unconfirmed'::varchar as approval_status,
       false::boolean as additive, 'candidate pending parent review'::varchar as nonadditive_reason,
       source_row, physical_page, page_number, y, bbox_json, record_kind, printed_text,
       kan_code, kan_label, kou_code, kou_label, printed_kan_total, printed_kou_total,
       moku_code, moku_label,
       current_text, current_amount, prior_text, prior_amount, change_text, change_amount,
       natl_text, natl_amount, metro_text, metro_amount, bond_text, bond_amount,
       other_src_text, other_src_amount, general_text, general_amount,
       setsu_no, setsu_label, setsu_text, setsu_amount,
       parent_moku_code, parent_moku_label, parent_moku_source_row, parent_evidence,
       description, source_amount_unit, source_url, source_sha256,
       wayback_url, wayback_capture,
       hive_jurisdiction, hive_year, hive_document_kind, hive_edition, hive_resource, hive_direction
from {{ ref('stg_132195__initial_detail_recovered') }}
