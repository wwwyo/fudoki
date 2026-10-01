{{ config(materialized = 'external', location = env_var('FUDOKI_INTERNAL_PACKAGE_DIR') ~ '/132047/account_names.csv', format = 'csv') }}
-- 科目（款・項・目）の名称と、法定マスタへの対応。**fudoki の判断を含む。**
--
-- 名称の出所は name_source が言う（source-csv = 原典 CSV の文字列そのまま /
-- statement-pdf = 事項別明細書 PDF の見出しから抽出した文字列そのまま /
-- settlement-pdf = 決算書 PDF の見出しから fudoki が解決した）。
-- canonical_fund は会計の名寄せ（fudoki の判断）。同じ制度を担う会計の
-- 呼び名は団体で違うので、比較は fund_label ではなく canonical_fund で行う。
-- 会計の内訳（帳簿上の区分・普通会計/公営事業会計の枠組み）は funds.csv が持つ。
-- master_* は一般会計なら地方自治法施行規則 別記の区分への対応で、**コードは団体ごとに
-- 法定とずれる**（法定の款11 災害復旧費を持たない市では以降が詰まる）ため、
-- コードではなくこの対応を介して団体をまたいで比較する。
-- 法定の特別会計（国民健康保険・介護保険・後期高齢者医療）は、一般会計の様式ではなく
-- **会計固有の調査票の勘定科目**（special_account_master）に当ててある。
-- master_kind = addition は法定に無い区分（様式の備考が認める追加）、
-- historical は現行様式から削除された旧法定区分。
-- master_* が付かないのは、対応する様式・調査票を持たない特別会計と、
-- **科目の名称がまだ得られていない団体 × 方向**（名称の根拠なしにコードで対応づけない）。
select
    fiscal_year, direction, fund_code, fund_label, canonical_fund,
    kan_code, kan_name, kou_code, kou_name, moku_code, moku_name,
    name_source,
    master_kan_code, master_kan_name, master_kou_code, master_kou_name,
    master_kind, master_basis
from {{ ref('core_fiscal_accounts') }}
where jurisdiction_code = '132047'
order by fiscal_year, direction, fund_code, cast(kan_code as integer),
         cast(kou_code as integer), cast(moku_code as integer)
