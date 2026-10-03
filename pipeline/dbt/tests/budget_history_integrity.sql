with h as (select * from {{ ref('int_fiscal_budget_history') }}),
     c as (select * from {{ ref('fiscal_expenditure_budget_changes') }}),
     i as (select * from {{ ref('fiscal_initial_expenditure_budget_lines') }}),
     l as (select * from {{ ref('fiscal_expenditure_settlement_links') }}),
     s as (select * from {{ ref('stg_132195__budget_history') }}),
     expected(target_key, initial_amount, delta_amount, reported_amount, executed_amount, links) as (
       values ('7-1-2',34553000::bigint,33300000::bigint,68814000::bigint,66261365::bigint,9),
              ('13-1-1',30000000::bigint,1980000::bigint,23761662::bigint,0::bigint,1)
     )
select 'target_totals' as problem, e.target_key as id from expected e
left join (select target_key, max(initial_yen) as initial_amount, sum(delta_yen) as delta_amount from h group by target_key) t using(target_key)
where t.initial_amount is distinct from e.initial_amount or t.delta_amount is distinct from e.delta_amount
union all
select 'unexpected_target', target_key from h where target_key not in (select target_key from expected)
union all
select 'adopted_issue_count', '132195:2023' from (select count(*) n, count(distinct amendment_number) issues from {{ ref('fiscal_datasets') }} where jurisdiction_code='132195' and fiscal_year=2023 and document_kind in ('budget','supplementary')) where n!=8 or issues!=8
union all
select 'history_cardinality', '132195:2023' where (select count(*) from h)!=5 or (select count(*) from c)!=3 or (select count(*) from l)!=10
union all
select 'source_rows_lost', '132195:2023' where (select count(*) from s)!=(select count(*) from {{ source('raw_132195_history','data') }})
union all
select 'duplicate_source', fiscal_line_id from s group by fiscal_line_id having count(*)!=1
union all
select 'missing_original_position', fiscal_line_id from h where page_number is null or json_array_length(bbox_json)!=4
union all
select 'incorrect_change', c.change_id from c left join h on h.fiscal_line_id=c.dataset_id||':'||c.source_row
where h.fiscal_line_id is null or h.record_kind!='change' or c.amount_delta is distinct from h.delta_yen
   or h.before_yen+h.delta_yen is distinct from h.after_yen or c.effective_at is distinct from h.effective_at
   or c.change_kind!='supplementary' or json_array_length(c.details_json)!=1
union all
select 'initial_not_in_mart', h.fiscal_line_id from h left join i using(fiscal_line_id)
where h.record_kind='initial' and (i.amount is distinct from h.initial_yen or i.budget_item_id is distinct from h.budget_item_id)
union all
select 'unconfirmed_setsu_fabricated', b.budget_item_id from {{ ref('fiscal_expenditure_budget_items') }} b join h using(budget_item_id)
where b.expenditure_setsu_id is not null or b.line_granularity!='origin_line'
union all
select 'settlement_correspondence', e.target_key from expected e
left join (
  select h.target_key,count(*) links,sum(a.amount) executed_amount,sum(p.value) reported_amount
  from l join h on h.budget_item_id=l.budget_item_id and h.record_kind='initial'
  join {{ ref('fiscal_settlement_expenditure_lines') }} a on a.fiscal_line_id=l.settlement_line_id
  join {{ ref('int_fiscal_amounts') }} p on p.fiscal_line_id=l.settlement_line_id and p.phase='adjusted'
  where l.match_status='confirmed' group by h.target_key
) t using(target_key)
where t.links is distinct from e.links or t.executed_amount is distinct from e.executed_amount or t.reported_amount is distinct from e.reported_amount
union all
select 'manual_report_differs', coalesce(s.fiscal_line_id,e.target_key) from (select * from s where record_kind='reported') s
full outer join expected e on e.target_key=s.kan_code||'-'||s.kou_code||'-'||s.moku_code
where s.fiscal_line_id is null or e.target_key is null or s.reported_amount is distinct from e.reported_amount or s.executed_amount is distinct from e.executed_amount or s.page_number is null
union all
select 'approval_missing', d.dataset_id from {{ ref('fiscal_datasets') }} d
where d.document_kind='supplementary' and (d.effective_at is null or not exists(select 1 from s where record_kind='approval' and table_id='approval-'||d.amendment_number))
union all
select 'duplicate_link', budget_item_id||':'||settlement_line_id from l group by budget_item_id,settlement_line_id having count(*)!=1

union all
select 'reported_cardinality', '132195:2023' where (select count(*) from s where record_kind='reported')!=2

union all
select 'source_values_changed','132195:2023' where exists(
  (select source_row,record_kind,fund_code,fund_label,kan_code,kou_code,moku_code,moku_label,initial_text,before_text,delta_text,after_text,reported_amount_text,executed_amount_text,page_number,bbox_json,printed_text from {{ source('raw_132195_history','data') }} except all select source_row,record_kind,fund_code,fund_label,kan_code,kou_code,moku_code,moku_label,initial_text,before_text,delta_text,after_text,reported_amount_text,executed_amount_text,page_number,bbox_json,printed_text from s)
  union all
  (select source_row,record_kind,fund_code,fund_label,kan_code,kou_code,moku_code,moku_label,initial_text,before_text,delta_text,after_text,reported_amount_text,executed_amount_text,page_number,bbox_json,printed_text from s except all select source_row,record_kind,fund_code,fund_label,kan_code,kou_code,moku_code,moku_label,initial_text,before_text,delta_text,after_text,reported_amount_text,executed_amount_text,page_number,bbox_json,printed_text from {{ source('raw_132195_history','data') }})
)
