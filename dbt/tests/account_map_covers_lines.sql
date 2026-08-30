-- **マスタの遵守。** 一般会計に現れる款・項は、名称が分かっている限り法定マスタへ解決すること。
--
-- 解決の経路は3つ（対応・名称の完全一致・追加の明示登録）で、どれにも当たらないのは
-- 「新しい団体の科目をマスタと突き合わせていない」状態。黙って配ると、
-- 横断の問い合わせがその団体の分だけ静かに欠ける。account_map.csv へ登録して直す。
--
-- ⚠️ 対象は**名称が分かっている**款・項だけ。名称の無い団体 × 方向
-- （決算資料 PDF が無い年度の科目、歳入の科目名を持たない団体）は
-- 突き合わせる材料が無いので、対応を要求せず保留のまま残す。
-- 名称も無く対応も無い状態は account_names.csv に null として正直に出る。
-- 特別会計は様式の対象外（施行規則の備考5・6）なので見ない。
with unresolved as (
    select
        jurisdiction_code, fiscal_year, direction, kan_code, kan_name, kou_code, kou_name,
        case
            -- ⚠️ **対応先が無いこと自体は誤りではない。** 止めたいのは
            -- 「突き合わせていない」状態で、款ごと historical（旧法定区分）や
            -- addition（様式の備考が条件付きで認める款）は突き合わせ済みの判断にあたる。
            when kan_name is not null and master_kan_code is null
                 and coalesce(master_kind, '') not in ('historical', 'addition')
                 then '款が account_map に無い'
            when kou_name is not null and master_kind is null then '項がマスタにも account_map にも無い'
        end as problem
    from {{ ref('core_budget_accounts') }}
    where fund_label = '一般会計'
)

select jurisdiction_code, direction, kan_code, kan_name, kou_code, kou_name, problem, count(*) as n
from unresolved
where problem is not null
group by all
order by jurisdiction_code, kan_code, kou_code
