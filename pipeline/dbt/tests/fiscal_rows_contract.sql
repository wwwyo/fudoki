with rows as (select * from {{ ref('int_fiscal__settlement_expenditure_rows') }}),
counts as (select source_table_key, count(*) as n from rows group by 1),
annotations as (
    select source_table_key, count(*) as n from {{ ref('stg_fiscal__nodes') }}
    where axis_header = '注記' group by 1
)
select t.source_table_key, 'missing_or_duplicated_row' as failure
from {{ source('fiscal_metadata', 'tables') }} t
left join counts c using (source_table_key)
left join annotations a using (source_table_key)
where coalesce(c.n, 0) <> t.nodes_row_count - coalesce(a.n, 0)
union all
select source_table_key, 'invalid_node' from rows
where node_kind is null or name is null or name = '' or axis_header is null or axis_header = ''
   or (parent_node_key is null and (node_kind <> '款' or axis_header <> subject_axis))
   or (axis_header = subject_axis and (node_kind not in ('款','項','目')
       or (code_text is null and node_kind in ('款', '項'))))
union all
-- node_id joins the key so numberless 目 (parent-based identity) never lump with their 項.
-- Tables printing the whole account agree on the amount; the shares of division tables
-- (所属, ADR 0030) are summed, and where a whole prints the node they add up to it.
select min(source_table_key), 'cross_table_subject_disagreement' from rows
where axis_header = subject_axis and node_kind in ('款', '項', '目')
group by jurisdiction_code, fiscal_year, document_kind, account_name, kan_code, kou_code, moku_code, node_id
having count(distinct name) <> 1
    or count(distinct amount_yen) filter (where division is null) > 1
    or (count(amount_yen) > 0 and count(amount_yen) <> count(*))
    or count(distinct parent_node_id) > 1
    or (count(*) filter (where division is null) > 0 and count(*) filter (where division is not null) > 0
        and sum(amount_yen) filter (where division is not null)
            is distinct from min(amount_yen) filter (where division is null))
union all
-- Two divisions print the same 節 of the same 目 as one node; a table never prints it twice.
select min(source_table_key), 'non_subject_id_collision' from rows
where axis_header <> subject_axis group by document_kind, node_id
having count(*) > 1 and (count(*) filter (where division is null) > 0
    or count(distinct source_table_key) <> count(*)
    or (count(amount_yen) > 0 and count(amount_yen) <> count(*)))
union all
-- A division prints its share of an account once; a second table of it would count it twice.
select min(source_table_key), 'duplicated_division' from {{ source('fiscal_metadata', 'tables') }}
where division is not null
group by jurisdiction_code, fiscal_year, document_kind, direction, account_name, division
having count(*) > 1
