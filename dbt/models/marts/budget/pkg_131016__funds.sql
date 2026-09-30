{{ config(materialized = 'external', location = '../data/budget/datapackages/131016/funds.csv', format = 'csv') }}
-- 会計の名寄せと帳簿上の区分。**fudoki の判断**（名寄せと枠組みへの割り振りは
-- 自治体が言っていないこと。根拠は basis に書いてある）。
--
-- fund_label（原典の会計名）→ canonical_fund（制度としての名寄せ）と、
-- その会計が帳簿上どの区分か（account_class）、普通会計/公営事業会計の
-- 枠組みのどちら側か（sector）。同じ制度を担う会計の呼び名は団体で違うので、
-- 団体をまたぐ比較は fund_label ではなく canonical_fund で行う。
select
    fund_label,
    canonical_fund,
    account_class,
    sector,
    basis
from {{ ref('fund_directory') }}
where jurisdiction_code = '131016'
order by fund_label
