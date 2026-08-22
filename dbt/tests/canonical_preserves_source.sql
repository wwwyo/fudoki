-- **原典との多重集合一致。** 行数だけでなく中身の集合が一致すること。
-- 行数が合っていても取り違えや重複があれば落ちる。
-- staging で trim しているので、原典側も trim して比べる（差は3セルと実測済み）。
with raw_cells as (
    select 'expenditure' as direction,
        [{{ trim_cell('"01会計"') }}, {{ trim_cell('"02款"') }}, {{ trim_cell('"03項"') }}, {{ trim_cell('"04目"') }},
         {{ trim_cell('"05事項"') }}, {{ trim_cell('"06節"') }}, {{ trim_cell('"07細々節"') }}, "08予算額"] as cells
    from {{ source('raw_132047', 'expenditure') }}
    union all
    select 'revenue',
        [{{ trim_cell('"01会計"') }}, {{ trim_cell('"02款"') }}, {{ trim_cell('"03項"') }}, {{ trim_cell('"04目"') }},
         {{ trim_cell('"05節"') }}, {{ trim_cell('"06細節"') }}, {{ trim_cell('"07細々節"') }}, "08予算額"] as cells
    from {{ source('raw_132047', 'revenue') }}
),
staged_cells as (
    select direction, [fund_source, kan_source, kou_source, moku_source, jikou_source, setsu_source,
                       saisaisetsu_source, cast(source_amount as varchar)] as cells
    from {{ ref('stg_132047__expenditure') }}
    union all
    select direction, [fund_source, kan_source, kou_source, moku_source, setsu_source, saisetsu_source,
                       saisaisetsu_source, cast(source_amount as varchar)] as cells
    from {{ ref('stg_132047__revenue') }}
),
counted as (
    select direction, cells, count(*) as n from raw_cells group by 1, 2
    union all
    select direction, cells, -count(*) from staged_cells group by 1, 2
)
select direction, cells, sum(n) as 差 from counted group by 1, 2 having sum(n) <> 0
