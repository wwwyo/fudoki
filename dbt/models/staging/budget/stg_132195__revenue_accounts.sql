-- 狛江市 歳入の科目名称（決算資料の歳入事項別明細から抽出）。抽出結果と1対1。
--
-- ⚠️ **これは原典ではない。** PDF のレイアウトから起こしたもので、抽出の時点で
-- 不可逆な操作が入っている（歳出の事業名と同じ扱い）。
-- ⚠️ **調定額が原典 CSV と一致した科目だけを下流が使う。** 抽出の誤り（特に OCR 経路）は
-- 金額の不一致として現れる。突合は tests/revenue_accounts_reconcile.sql が見る。
select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    ordinal,
    kan_code,
    kou_code,
    moku_code,
    {{ trim_cell('kan_name') }}  as kan_name,
    {{ trim_cell('kou_name') }}  as kou_name,
    {{ trim_cell('moku_name') }} as moku_name,
    choutei_yen,
    -- 抽出の経路。text = PDF のテキストそのまま / ocr = Tesseract の読み取り（誤読あり）
    mode
from {{ source('raw_132195_revenue_accounts', 'data') }}
