{{ fiscal_csv('131016', 'initial_expenditure_moku_setsu') }}
select observation_id, dataset_id, explanation_dataset_id, jurisdiction_code, fiscal_year,
       document_kind, origin_sha256, source_table_id, source_row, fund_label, canonical_fund,
       kan_code, kan_label, kou_code, kou_label, moku_code, moku_label, setsu_code, setsu_label,
       source_amount, source_amount_unit, amount, phase, line_granularity, project_setsu_linkage,
       expenditure_setsu_id, setsu_mapping_status, source_page, source_bbox, reconciled, source_json
from {{ ref('fiscal_initial_expenditure_moku_setsu') }}
