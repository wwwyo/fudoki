{% set detail_schema = '[{"path":"JSON","amount":"BIGINT","fiscalLineId":"VARCHAR","sourceRow":"BIGINT"}]' %}
with details as (
  select l.fiscal_line_id as parent_id, l.dataset_id, x.*
  from {{ ref('fiscal_settlement_expenditure_setsu_lines') }} l,
       unnest(from_json(l.details_json, '{{ detail_schema }}')) t(x)
), problems(problem, id) as (
  select 'unresolved_printed_setsu', fiscal_line_id
  from {{ ref('int_settlement_expenditure_setsu_lines') }}
  where setsu_present and expenditure_setsu_id is null
  union all
  select 'invalid_setsu_period', l.fiscal_line_id
  from {{ ref('fiscal_settlement_expenditure_setsu_lines') }} l
  join {{ ref('int_fiscal_datasets') }} d using(dataset_id)
  left join {{ ref('fiscal_expenditure_setsu_master') }} m using(expenditure_setsu_id)
  where l.expenditure_setsu_id is not null and (
    m.expenditure_setsu_id is null
    or d.fiscal_year < coalesce(m.valid_from_fiscal_year, -9999)
    or d.fiscal_year > coalesce(m.valid_to_fiscal_year, 9999))
  union all
  select 'aggregated_without_setsu', fiscal_line_id
  from {{ ref('fiscal_settlement_expenditure_setsu_lines') }}
  where line_granularity = 'expenditure_setsu' and expenditure_setsu_id is null
  union all
  select 'details_amount_mismatch', l.fiscal_line_id
  from {{ ref('fiscal_settlement_expenditure_setsu_lines') }} l
  left join (select parent_id, sum(amount) as total from details group by parent_id) d
    on d.parent_id = l.fiscal_line_id
  where l.amount is distinct from d.total
  union all
  select 'origin_line_missing_or_reused', coalesce(o.fiscal_line_id, d.fiscalLineId)
  from {{ ref('fiscal_settlement_expenditure_lines') }} o
  full outer join (select fiscalLineId, count(*) as n from details group by fiscalLineId) d
    on o.fiscal_line_id = d.fiscalLineId
  where o.fiscal_line_id is null or d.n is distinct from 1
  union all
  select 'origin_value_or_dataset_changed', d.fiscalLineId
  from details d
  join {{ ref('fiscal_settlement_expenditure_lines') }} o on o.fiscal_line_id = d.fiscalLineId
  where d.amount is distinct from o.amount or d.dataset_id is distinct from o.dataset_id
  union all
  select 'dataset_total_differs', coalesce(a.dataset_id, o.dataset_id)
  from (select dataset_id, sum(amount) as total
        from {{ ref('fiscal_settlement_expenditure_setsu_lines') }} group by dataset_id) a
  full outer join (select dataset_id, sum(amount) as total
        from {{ ref('fiscal_settlement_expenditure_lines') }} group by dataset_id) o using(dataset_id)
  where a.total is distinct from o.total
)
select * from problems
