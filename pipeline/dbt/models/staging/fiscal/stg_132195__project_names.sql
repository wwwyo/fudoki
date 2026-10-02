-- 狛江市 事業名（決算資料 PDF から抽出）。抽出結果と1対1。
--
-- ⚠️ **これは原典ではない。** CSV の staging は原典と1対1で復元一致まで検査できるが、
-- こちらは PDF のレイアウトから起こしたもので、抽出の時点で不可逆な操作が入っている。
-- 「原典に忠実」と言えるのは CSV 側だけで、ここは抽出物に忠実、が正確な言い方になる。
--
-- ⚠️ **名称と大事業コードの対応づけはここでやらない。** それは判断なので core。
select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    ordinal,
    kan_code,
    kou_code,
    moku_code,
    -- ⚠️ **科目の名称は CSV の原典に無い。** 決算書 PDF の見出しにだけある。
    -- 以前この抽出器は名称を捨てており、そのせいで「PDF にも無い」と誤って結論し、
    -- 狛江市の COFOG が款までしか決まらない理由にしていた。
    {{ trim_cell('kan_name') }}  as kan_name,
    {{ trim_cell('kou_name') }}  as kou_name,
    {{ trim_cell('moku_name') }} as moku_name,
    {{ trim_cell('project_name') }} as project_name,
    amount_thousand_yen,
    -- その目の合計と事業の合計が突き合った目か。**突合できない目からは名前を採らない。**
    -- 抽出漏れがあると目の合計に届かないので、そこを境界にする。
    moku_reconciled
from {{ source('raw_132195_project_names', 'data') }}
