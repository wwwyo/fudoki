-- 三鷹市 歳出。原典と1対1。
-- **列名の付け替えと型付けだけ。** 判断（分類・名寄せ・推定）はここに書かない。
-- 行を増減させてもいけない（1対1は tests/staging_is_one_to_one.sql が縛る）。
select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    direction,
    source_row,
    {{ trim_cell('"01会計"') }} as fund_source,
    {{ trim_cell('"02款"') }} as kan_source,
    {{ trim_cell('"03項"') }} as kou_source,
    {{ trim_cell('"04目"') }} as moku_source,
    {{ trim_cell('"05事項"') }} as jikou_source,
    {{ trim_cell('"06節"') }} as setsu_source,
    {{ trim_cell('"07細々節"') }} as saisaisetsu_source,
    -- 原典の単位は千円。円への換算は判断ではないが core で行う（正本は原典の値を保つ）。
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
    regexp_extract(jikou_source, '^(\d{2})') as jikou_code,
    regexp_replace(jikou_source, '^\d{2}', '') as jikou_label,
    regexp_extract(setsu_source, '^(\d{2})') as setsu_code,
    regexp_replace(setsu_source, '^\d{2}', '') as setsu_label,
    regexp_extract(saisaisetsu_source, '^(\d{2})') as saisaisetsu_code,
    regexp_replace(saisaisetsu_source, '^\d{2}', '') as saisaisetsu_label
,
    -- 識別子。**公開 API の一部**なので導出を変えると permalink が全滅する。
    -- 構成要素はコードのパスではなく**セル全文**（コード + 名称）。
    -- 三鷹市の細々節は同じ節の下でコードを再利用しており（実測 710 箇所・1,615 行）、
    -- コードのパスだと 5,613 行が 4,708 通りにしかならない。
    -- 区切りは U+001F（原典に現れない制御文字）。
    -- **phase は partition から取る。** 固定値にすると、補正予算を足したとき
    -- partition の phase と staging の phase が食い違う（取得側は既に phase で切っている）。
    phase as phase_id,
    jurisdiction_code || ':' || fiscal_year || ':' || direction || ':' || phase || ':'
        || substr(sha256(
            jurisdiction_code || chr(31) || fiscal_year || chr(31) || direction || chr(31) || phase
            || chr(31) || fund_source || chr(31) || kan_source || chr(31) || kou_source || chr(31) || moku_source || chr(31) || jikou_source || chr(31) || setsu_source || chr(31) || saisaisetsu_source
        ), 1, 16) as budget_line_id,
    cast("08予算額" as bigint) as source_amount
from {{ source('raw_132047', 'expenditure') }}
