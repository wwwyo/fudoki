-- **科目カタログの主キーが一意か。** datapackage.json は
-- (fiscal_year, direction, fund_code, kan_code, kou_code, moku_code) を主キーと宣言している。
-- core は distinct で重複を抑制しているが、名称解決や対応表の join が多重に当たると
-- **同じ科目が違う名称・対応で2行**になり、distinct では消えず主キーの宣言が嘘になる。
select jurisdiction_code, fiscal_year, direction, fund_code, kan_code, kou_code, moku_code,
       count(*) as n
from {{ ref('core_budget_accounts') }}
group by all
having count(*) > 1
