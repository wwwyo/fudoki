{{ config(severity = 'warn') }}
-- **警告。落とさないが毎回見える。**
--
-- 原典のセルに前後の空白が入っていることを報告する。staging で trim しているので
-- 下流には影響しないが、**黙って直すと次に読んだ者が原典の状態を誤解する**。
-- TS 版はここを報告せずに trim しており、原典に全角スペースが入っていることを
-- 誰も知らないまま1団体目を配っていた。
--
-- 件数が増えたら原典側の入力運用が変わった合図でもある。
with cells as (
    select direction, source_row, unnest([
        "01会計", "02款", "03項", "04目", "05事項", "06節", "07細々節"
    ]) as cell
    from {{ source('raw_132047', 'expenditure') }}

    union all

    select direction, source_row, unnest([
        "01会計", "02款", "03項", "04目", "05節", "06細節", "07細々節"
    ]) as cell
    from {{ source('raw_132047', 'revenue') }}
)

select direction, source_row, cell, '前後に空白がある。staging で trim した' as note
from cells
where cell is not null and cell <> {{ trim_cell('cell') }}
