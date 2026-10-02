-- **収録した会計がすべて名寄せ辞書にあるか。**
-- fund_directory に無い会計は canonical_fund が null になり、
-- 比較も sector による畳み込みも静かに対象から落ちる。
with lines as (
    select distinct jurisdiction_code, fund_label from {{ ref('core_fiscal_lines') }}
    union
    select distinct jurisdiction_code, fund_label from {{ ref('core_revenue_lines') }}
)
select l.jurisdiction_code, l.fund_label
from lines as l
left join {{ ref('fund_directory') }} as d
    on d.jurisdiction_code = l.jurisdiction_code and d.fund_label = l.fund_label
where d.fund_label is null
