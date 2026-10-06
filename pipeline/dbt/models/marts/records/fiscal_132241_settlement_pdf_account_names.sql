{{ config(materialized='table') }}
-- All printed moku names, including reserve controls without legal children.
-- The catalog belongs to its control dataset; it does not link funding projects.
select distinct dataset_id, jurisdiction_code, fiscal_year, origin_sha256, origin_url,
       fund_label, canonical_fund, kan as kan_code,
       json_extract_string(source_observation_json, '$.kan_position.name') as kan_label,
       kou as kou_code,
       json_extract_string(source_observation_json, '$.kou_position.name') as kou_label,
       moku as moku_code, moku_label,
       'printed-settlement-book' as name_source,
       'unconfirmed' as account_mapping_status
from {{ ref('int_132241__settlement_pdf_moku_controls') }}
