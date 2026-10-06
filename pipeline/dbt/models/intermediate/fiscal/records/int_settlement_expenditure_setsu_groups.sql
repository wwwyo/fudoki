with lines as (
  select *,
    count(distinct coalesce(cofog_code, '') || chr(31) || coalesce(cofog_status, '')
      || chr(31) || coalesce(cofog_basis, '') || chr(31) || coalesce(consolidation, '')
      || chr(31) || coalesce(counterpart_fund, ''))
      over (partition by dataset_id, group_path_key, expenditure_setsu_id) as classifications
  from {{ ref('int_settlement_expenditure_setsu_lines') }}
)
select *,
  case when expenditure_setsu_id is not null and classifications = 1
       then 'expenditure_setsu' else 'origin_line' end as line_granularity,
  case when expenditure_setsu_id is not null and classifications = 1
       then dataset_id || ':settlement-setsu:' || substr(sha256(
         group_path_key || chr(31) || expenditure_setsu_id), 1, 16)
       else fiscal_line_id end as settlement_group_id
from lines
