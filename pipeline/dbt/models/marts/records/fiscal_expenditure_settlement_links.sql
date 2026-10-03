{{ config(materialized='table') }}
select null::varchar as budget_item_id, null::varchar as settlement_line_id, null::varchar as match_status, null::varchar as match_group_id, null::varchar as basis where false
