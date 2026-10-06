{{ config(materialized='table') }}
select '132047'::varchar as jurisdiction_code,
  source_key, fiscal_year, document_kind, account, amendment, direction, row_type, grain, name, printed_text, printed_amounts, amount_semantics, phase, page, line, indent, col_context, table_index, section, sec_i, ordinal, kan_amount, row_label, cells, extra
from {{ ref('int_mitaka_initial2026') }}
