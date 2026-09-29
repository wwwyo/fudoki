{{ config(materialized = 'external', location = '../data/budget/datapackages/132195/interfund_transfers.csv', format = 'csv') }}
-- 会計間移転の宣言。**fudoki の判断そのもの。**
-- ここに宣言した行が cofog.csv で cofog_consolidation=eliminated になっている。
-- 行・項・款のどの粒度でも宣言できる（空のキーはワイルドカード）。
-- amount_yen が書かれた行は、同じ科目に複数の受け皿があるとき額で行を確定したもの。
-- 宣言が無い繰出金・繰入金は retained のまま（受け皿が確定できないため）。
select
    fiscal_year,
    direction,
    fund_label,
    kan_code,
    kou_code,
    moku_code,
    setsu_code,
    amount_yen,
    counterpart_fund,
    basis
from {{ ref('interfund_transfers') }}
where jurisdiction_code = '132195'
order by fiscal_year, direction, fund_label, kan_code, kou_code, moku_code, setsu_code
