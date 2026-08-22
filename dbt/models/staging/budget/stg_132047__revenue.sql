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
    {{ trim_cell('"01会計"') }} as fund_source,
    {{ trim_cell('"02款"') }} as kan_source,
    {{ trim_cell('"03項"') }} as kou_source,
    {{ trim_cell('"04目"') }} as moku_source,
    {{ trim_cell('"05節"') }} as setsu_source,
    {{ trim_cell('"06細節"') }} as saisetsu_source,
    {{ trim_cell('"07細々節"') }} as saisaisetsu_source,
    -- コードと名称の分離。三鷹市は先頭2桁がコード（実測）。
    -- 桁数は団体ごとに違いうるので、団体別モデルの中に閉じる。
    regexp_extract(fund_source, '^(\d{2})') as fund_code,
    regexp_replace(fund_source, '^\d{2}', '') as fund_label,
    regexp_extract(kan_source, '^(\d{2})') as kan_code,
    regexp_replace(kan_source, '^\d{2}', '') as kan_label,
    regexp_extract(kou_source, '^(\d{2})') as kou_code,
    regexp_replace(kou_source, '^\d{2}', '') as kou_label,
    regexp_extract(moku_source, '^(\d{2})') as moku_code,
    regexp_replace(moku_source, '^\d{2}', '') as moku_label,
    regexp_extract(setsu_source, '^(\d{2})') as setsu_code,
    regexp_replace(setsu_source, '^\d{2}', '') as setsu_label,
    regexp_extract(saisetsu_source, '^(\d{2})') as saisetsu_code,
    regexp_replace(saisetsu_source, '^\d{2}', '') as saisetsu_label,
    regexp_extract(saisaisetsu_source, '^(\d{2})') as saisaisetsu_code,
    regexp_replace(saisaisetsu_source, '^\d{2}', '') as saisaisetsu_label
,
    -- 識別子。**公開 API の一部**なので導出を変えると permalink が全滅する。
    -- 構成要素はコードのパスではなく**セル全文**（コード + 名称）。
    -- 三鷹市の細々節は同じ節の下でコードを再利用しており（実測 710 箇所・1,615 行）、
    -- コードのパスだと 5,613 行が 4,708 通りにしかならない。
    -- 区切りは U+001F（原典に現れない制御文字）。
    'approved' as phase_id,
    jurisdiction_code || ':' || fiscal_year || ':' || direction || ':approved:'
        || substr(sha256(
            jurisdiction_code || chr(31) || fiscal_year || chr(31) || direction || chr(31) || 'approved'
            || chr(31) || fund_source || chr(31) || kan_source || chr(31) || kou_source || chr(31) || moku_source || chr(31) || setsu_source || chr(31) || saisetsu_source || chr(31) || saisaisetsu_source
        ), 1, 16) as budget_line_id,
    cast("08予算額" as bigint) as source_amount
from {{ source('raw_132047', 'revenue') }}
