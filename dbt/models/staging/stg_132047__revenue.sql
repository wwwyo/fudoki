-- 三鷹市 歳入。原典と1対1。
--
-- ⚠️ **歳出と階層が違う。** 歳出は 会計/款/項/目/事項/節/細々節、
-- 歳入は 会計/款/項/目/節/細節/細々節。どちらも7階層だが、
-- 歳出の「事項」の位置に歳入は何も持たず、代わりに節の下に「細節」がある。
-- 設計時は歳入を6階層と想定していたが、細々節を落とすと識別子が7組衝突する。
select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    direction,
    source_row,
    "01会計"    as fund_source,
    "02款"      as kan_source,
    "03項"      as kou_source,
    "04目"      as moku_source,
    "05節"      as setsu_source,
    "06細節"    as saisetsu_source,
    "07細々節"  as saisaisetsu_source,
    cast("08予算額" as bigint) as source_amount
from {{ source('raw_132047', 'revenue') }}
