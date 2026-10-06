{{ config(materialized='table') }}
-- 独立観測の公開 registry。統制・説明は加算しない。
select * from {{ ref('int_native__datasets') }}
