-- 款・項・目の名称。**原典の CSV に無く、決算書 PDF の見出しにだけある。**
--
-- ⚠️ **これは判断である。** 「PDF の見出し `２. １. １. 一般管理費` は、CSV の
-- (款2, 項1, 目1) のことだ」と決めているのは fudoki で、市がそう言っているわけではない。
-- だから staging ではなく core に置き、配布物では正本と別のリソースに出す。
--
-- ⚠️ **以前この経路は存在せず、狛江市の COFOG は款で止まっていた**（金額で 25.9% が
-- 分類不能）。理由を「款・項・目の名称は決算書 PDF にも無い」と書いていたが誤りで、
-- 実際は抽出器が科目欄から数字だけを拾って名称を捨てていた。
-- **自分の抽出結果の欠落を、資料の性質だと読み替えていた。**
--
-- ⚠️ **年度をまたいで外挿しない。** 名称が採れた年度にだけ付ける。
-- 狛江市は 2020 年度に節のコードが振り直されており、科目のコードが年度をまたいで
-- 同じものを指す保証が原典から得られない。PDF が無い 2018〜2019年度は名称なしのまま残す。
with pdf as (
    select
        jurisdiction_code,
        fiscal_year,
        kan_code, kou_code, moku_code,
        kan_name, kou_name, moku_name
    from {{ ref('stg_132195__project_names') }}
),

-- 同じ目の中で名称が割れていないか。割れたら**どちらも採らない**（捏造しない）。
resolved as (
    select
        jurisdiction_code,
        fiscal_year,
        -- PDF の事項別明細は一般会計だけを載せている。特別会計へは広げない。
        '1' as fund_code,
        kan_code, kou_code, moku_code,
        min(kan_name)  as kan_name,
        min(kou_name)  as kou_name,
        min(moku_name) as moku_name,
        count(distinct kan_name)  as kan_variants,
        count(distinct kou_name)  as kou_variants,
        count(distinct moku_name) as moku_variants
    from pdf
    group by all
)

select
    jurisdiction_code,
    fiscal_year,
    fund_code,
    kan_code, kou_code, moku_code,
    case when kan_variants  = 1 then kan_name  end as kan_name,
    case when kou_variants  = 1 then kou_name  end as kou_name,
    case when moku_variants = 1 then moku_name end as moku_name,
    -- 名称の出所。正本の列と混同されないよう、判断の側だと分かる形で持つ。
    '決算書 PDF の事項別明細の見出し' as name_basis
from resolved
