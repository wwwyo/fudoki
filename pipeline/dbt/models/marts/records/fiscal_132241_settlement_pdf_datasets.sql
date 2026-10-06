{{ config(materialized='table') }}
-- Public registry of independent observations; controls remain nonadditive.
select * from {{ ref('int_132241__settlement_pdf_datasets') }}
