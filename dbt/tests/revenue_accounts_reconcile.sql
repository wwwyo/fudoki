-- **歳入の科目名称の突合。** 抽出した調定額が原典 CSV と目単位で一致すること。
--
-- 科目名称は PDF から起こした判断で、原典との復元一致が成立しない。
-- 代わりに、同じ行が持つ調定額を原典と突き合わせる — 抽出の誤り
-- （行のずれ・階層の混線・OCR の誤読）は金額の不一致として現れる。
--
-- ⚠️ 対象は**下流が名称に使う年度だけ**（= テキスト抽出の 2023）。
-- OCR 経路（2020〜2022）は誤読が多く名称に使っていないので、ここでも見ない
-- （見ると OCR の既知の誤読で常に落ち、検査が黙殺される）。
-- ⚠️ 調定累計は staging に載っていない列なので raw を直接読む。
with pdf as (
    select fiscal_year, kan_code, kou_code, moku_code, moku_name, choutei_yen
    from {{ ref('stg_132195__revenue_accounts') }}
    where fiscal_year = 2023
),

source_csv as (
    select
        cast(year as integer) as fiscal_year,
        cast(款 as varchar)   as kan_code,
        cast(項 as varchar)   as kou_code,
        cast(目 as varchar)   as moku_code,
        sum(cast("調定累計(円)" as bigint)) as choutei_yen
    from read_parquet('../data/budget/raw/jurisdiction=132195/year=2023/phase=*/direction=revenue/data.parquet', hive_partitioning = true)
    where 会計 = '1'
    group by all
)

select p.fiscal_year, p.kan_code, p.kou_code, p.moku_code, p.moku_name,
       p.choutei_yen as pdf_yen, c.choutei_yen as csv_yen
from pdf as p
left join source_csv as c using (fiscal_year, kan_code, kou_code, moku_code)
where p.choutei_yen is distinct from c.choutei_yen
