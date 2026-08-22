-- 三鷹市 歳出。原典と1対1。
-- **列名の付け替えと型付けだけ。** 判断（分類・名寄せ・推定）はここに書かない。
-- 行を増減させてもいけない（1対1は tests/staging_is_one_to_one.sql が縛る）。
select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    direction,
    source_row,
    "01会計"    as fund_source,
    "02款"      as kan_source,
    "03項"      as kou_source,
    "04目"      as moku_source,
    "05事項"    as jikou_source,
    "06節"      as setsu_source,
    "07細々節"  as saisaisetsu_source,
    -- 原典の単位は千円。円への換算は判断ではないが core で行う（正本は原典の値を保つ）。
    cast("08予算額" as bigint) as source_amount
from {{ source('raw_132047', 'expenditure') }}
