{{ config(tags=['komae-recovered']) }}
-- Full-fidelity staging: ALL 47 printed-origin columns verbatim (typed),
-- incl. `y` (row vertical offset) and `physical_page` preserved under its
-- original name; `page_number` is an explicit documented rename alias.
-- The six hive-partition fields are kept under hive_* names as metadata,
-- not confused with printed columns.
select
       -- 47 printed columns, verbatim
       dataset_id, fiscal_line_id, fiscal_year,
       source_row, physical_page, physical_page as page_number, y, bbox_json,
       record_kind, printed_text,
       kan_code, kan_label, kou_code, kou_label, printed_kan_total, printed_kou_total,
       moku_code, moku_label,
       current_text, current_amount, prior_text, prior_amount, change_text, change_amount,
       natl_text, natl_amount, metro_text, metro_amount, bond_text, bond_amount,
       other_src_text, other_src_amount, general_text, general_amount,
       setsu_no, setsu_label, setsu_text, setsu_amount,
       parent_moku_code, parent_moku_label, parent_moku_source_row, parent_evidence,
       description, source_amount_unit, source_url, source_sha256,
       wayback_url, wayback_capture,
       -- hive-partition metadata (not printed origin columns)
       '132195'::varchar as hive_jurisdiction,
       cast(year_p as integer) as hive_year,
       'budget'::varchar as hive_document_kind,
       edition_p as hive_edition,
       resource_id as hive_resource,
       direction_p as hive_direction
from {{ source('raw_132195_recovered_detail', 'data') }}
