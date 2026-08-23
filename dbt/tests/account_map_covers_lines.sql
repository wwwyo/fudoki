-- **マスタの遵守。** 一般会計の歳出に現れる款・項は、すべて法定マスタへ解決すること。
--
-- 解決の経路は3つ（対応・名称の完全一致・追加の明示登録）で、どれにも当たらないのは
-- 「新しい団体の科目をマスタと突き合わせていない」状態。黙って配ると、
-- 横断の問い合わせがその団体の分だけ静かに欠ける。account_map.csv へ登録して直す。
--
-- ⚠️ 対象は**名称が分かっている**款・項だけ。狛江市の 2018〜2019年度は
-- 決算資料 PDF が無く名称を解決できないので、突き合わせる材料が無い
-- （name が null の行は款の対応だけを要求する）。
-- 特別会計は様式の対象外（施行規則の備考6）なので見ない。
with unresolved as (
    select
        jurisdiction_code, fiscal_year, kan_code, kan_name, kou_code, kou_name,
        case
            when master_kan_code is null then '款が account_map に無い'
            when kou_name is not null and master_kind is null then '項がマスタにも account_map にも無い'
        end as problem
    from {{ ref('core_budget_accounts') }}
    where direction = 'expenditure' and fund_label = '一般会計'
)

select jurisdiction_code, kan_code, kan_name, kou_code, kou_name, problem, count(*) as n
from unresolved
where problem is not null
group by all
order by jurisdiction_code, kan_code, kou_code
