{{ config(materialized='table') }}
-- Source words and printed controls are nonadditive proof, never fiscal leaves.
select * from {{ ref('int_132241__settlement_pdf_legal_setsu') }}
