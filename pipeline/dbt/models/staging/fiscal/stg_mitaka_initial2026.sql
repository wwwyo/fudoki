select
  source_key, fiscal_year, document_kind, account, amendment, direction, row_type, grain, name, printed_text, printed_amounts, amount_semantics, phase, page, line, indent, col_context, table_index, section, sec_i, ordinal, kan_amount, row_label, cells, extra
from {{ source('raw_mitaka_initial2026', 'initial_observation') }}
