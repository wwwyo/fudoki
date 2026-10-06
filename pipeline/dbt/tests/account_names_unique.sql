-- **科目カタログの主キーが一意か。** datapackage.json は
-- (dataset_id, fund_code, fund_label, kan_code, kou_code, moku_code) を主キーと宣言している。
-- 予算と決算の改称を区別し、会計コードがない原典では会計名称も識別に使う。
-- core は distinct で重複を抑制しているが、名称解決や対応表の join が多重に当たると
-- **同じ科目が違う名称・対応で2行**になり、distinct では消えず主キーの宣言が嘘になる。
select jurisdiction_code, fiscal_year, direction, dataset_id, fund_code, fund_label, kan_code, kou_code, moku_code,
       count(*) as n
from {{ ref('core_fiscal_accounts') }}
group by all
having count(*) > 1
