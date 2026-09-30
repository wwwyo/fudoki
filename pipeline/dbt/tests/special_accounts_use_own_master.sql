-- **特別会計の款が一般会計のマスタに写っていないか。**
-- 同名の款（総務費など）が一般会計の区分に写ると、横断の集計が会計をまたいで混ざる。
-- 特別会計の master_* は会計固有の調査票の勘定科目（special_account_master）に限る。
with special as (
    select a.*
    from {{ ref('core_fiscal_accounts') }} as a
    join {{ ref('fund_directory') }} as fd
        on fd.jurisdiction_code = a.jurisdiction_code and fd.fund_label = a.fund_label
    where fd.account_class = '特別会計'
)

select s.jurisdiction_code, s.fiscal_year, s.direction, s.fund_label, s.kan_code,
       s.master_kan_code, s.master_kan_name
from special as s
left join {{ ref('special_account_master') }} as m
    on  m.canonical_fund = s.canonical_fund
    and m.direction      = s.direction
    and m.kan_code       = s.master_kan_code
where s.master_kan_code is not null
  and m.kan_code is null
