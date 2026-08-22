-- **識別子が既に配布したものと一致すること。TS 版を落とすまでの検査。**
--
-- budget_line_id は発言単位の permalink と同じ性質を持つ公開 API で、
-- 導出を変えると配布済みの参照が全滅する。移行で変えていないことをここで示す。
--
-- 実際に1行ずれた（`01郵便料　` の末尾の全角スペースを TS が黙って trim していた）。
-- 検査が無ければ気づかないまま別の識別子を配っていた。
with published as (
    select budget_line_id, cast(source_row as bigint) as source_row, 'expenditure' as direction
    from read_csv('../data/packages/132047/2024/expenditure.csv', header = true, all_varchar = true)

    union all

    select budget_line_id, cast(source_row as bigint), 'revenue'
    from read_csv('../data/packages/132047/2024/revenue.csv', header = true, all_varchar = true)
),

built as (
    select budget_line_id, source_row, direction from {{ ref('stg_132047__expenditure') }}
    union all
    select budget_line_id, source_row, direction from {{ ref('stg_132047__revenue') }}
)

select
    coalesce(p.direction, b.direction)   as direction,
    coalesce(p.source_row, b.source_row) as source_row,
    p.budget_line_id                     as published_id,
    b.budget_line_id                     as built_id
from published as p
full outer join built as b on p.source_row = b.source_row and p.direction = b.direction
where p.budget_line_id is distinct from b.budget_line_id
