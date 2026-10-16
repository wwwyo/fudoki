-- Children sums must match the printed parent on the same axis. Axes without any
-- printed amount (e.g. funding-source breakdowns excluded from totals) carry
-- nothing to reconcile, so they never fail the sum check; a parent holding an
-- amount while its same-axis subtree prints none is reported separately below.
-- A division's table (所属, ADR 0030) prints its share only, so its tree is checked
-- within the table (scope = the table); the summed tree is checked where a table
-- printing the whole stands for the node (scope '').
with recursive rows as (
    select * from {{ ref('int_fiscal__settlement_expenditure_rows') }}
), scoped as (
    select '' as scope, n.node_id, n.parent_node_id, n.document_kind, n.axis, n.amount_yen,
        n.jurisdiction_code, n.fiscal_year, n.account_name, n.source_page, n.code, n.name
    from {{ ref('int_fiscal__settlement_expenditure_nodes') }} n
    where not exists (
        select 1 from rows r where r.document_kind = n.document_kind and r.node_id = n.node_id
            and r.division is not null
    ) or exists (
        select 1 from rows r where r.document_kind = n.document_kind and r.node_id = n.node_id
            and r.division is null
    )
    union all
    select r.source_table_key, r.node_id, r.parent_node_id, r.document_kind, r.axis_header, r.amount_yen,
        r.jurisdiction_code, r.fiscal_year, r.account_name, r.physical_page, r.code_text, r.name
    from rows r where r.division is not null
), nodes as (
    -- Whether a node has children on its own axis, read here because a third reference
    -- to a CTE does not bind inside the recursive part below.
    select s.*, exists (
        select 1 from scoped c where c.scope = s.scope and c.parent_node_id = s.node_id
            and c.axis = s.axis and c.document_kind = s.document_kind
    ) as has_axis_children
    from scoped s
), child_values as (
    select scope, parent_node_id as checked_node_id, document_kind, axis, node_id, amount_yen, has_axis_children
    from nodes where parent_node_id is not null
    union all
    select v.scope, v.checked_node_id, v.document_kind, v.axis, c.node_id, c.amount_yen, c.has_axis_children
    from child_values v join nodes c on c.scope = v.scope and c.parent_node_id = v.node_id
        and c.axis = v.axis and c.document_kind = v.document_kind
    where v.amount_yen is null
), children as (
    -- Missing print uses descendants on the same axis; an empty leaf contributes zero.
    -- Stop each branch at its first printed value, retaining separate breakdown axes.
    select scope, checked_node_id, document_kind, axis, sum(coalesce(amount_yen, 0)) as amount_yen
    from child_values v
    where v.amount_yen is not null or not v.has_axis_children
    group by 1,2,3,4
), printed_axes as (
    -- Axes without any printed amount (e.g. funding-source breakdowns excluded from
    -- totals) have nothing to reconcile, so they never fail the sum check.
    select distinct scope, checked_node_id, document_kind, axis from child_values where amount_yen is not null
)
select p.node_id, 'children_sum' as failure
from nodes p
join children c on c.scope = p.scope and c.checked_node_id = p.node_id and c.document_kind = p.document_kind
join printed_axes a on a.scope = c.scope and a.checked_node_id = c.checked_node_id
    and a.document_kind = c.document_kind and a.axis = c.axis
where p.amount_yen is not null and c.amount_yen <> p.amount_yen
    -- A difference the original prints and the layout file declares (`source_inconsistencies`) passes only
    -- when the page, parent, printed value and children's sum all match the declaration.
    and not exists (
        select 1 from {{ source('fiscal_metadata', 'source_inconsistencies') }} d
        where d.jurisdiction_code = p.jurisdiction_code and d.fiscal_year = p.fiscal_year
            and d.document_kind = p.document_kind and d.account_name = p.account_name
            and d.axis = c.axis and d.page = p.source_page
            and d.parent_code is not distinct from p.code and d.parent_name = p.name
            and d.printed_yen = p.amount_yen and d.children_sum_yen = c.amount_yen
    )
union all
-- A parent with a nonzero printed amount whose same-axis subtree prints no amount
-- at all would otherwise escape the sum check above, so it fails here as missing
-- data. A zero-amount parent with an amount-less subtree is consistent (all zero)
-- and stays out, as do axes that never carry amounts. So does a parent with exactly
-- one same-axis child that prints no amount: the original prints a lone child's
-- amount once, on the parent row. The child stays NULL; nothing is distributed.
select p.node_id, 'missing_child_amounts' as failure
from nodes p
where coalesce(p.amount_yen, 0) <> 0
    and p.has_axis_children
    and not exists (
        select 1 from printed_axes a
        where a.scope = p.scope and a.checked_node_id = p.node_id and a.document_kind = p.document_kind
            and a.axis = p.axis
    )
    and not exists (
        select 1 from nodes c
        where c.scope = p.scope and c.parent_node_id = p.node_id and c.axis = p.axis
            and c.document_kind = p.document_kind and c.amount_yen is null
            and (select count(*) from nodes s
                where s.scope = p.scope and s.parent_node_id = p.node_id and s.axis = p.axis
                    and s.document_kind = p.document_kind) = 1
    )
