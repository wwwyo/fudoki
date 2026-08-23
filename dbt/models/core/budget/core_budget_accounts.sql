-- 科目（款・項・目）の一覧と、法定マスタへの解決。**団体をまたいで同じ形。**
--
-- 名称の出所は団体で違う。三鷹市は原典 CSV の各行に名称があり、狛江市は
-- 原典に無いので決算書 PDF の見出しから解決した（core_budget_account_names）。
-- どちらも (団体, 年度, 会計, 款, 項, 目) → 名称という同じ形へ畳み、
-- **どこから来た名称かを name_source で区別する**（事実と判断を列で見分けられるように）。
--
-- マスタへの解決は3段で当てる。
--   1. account_map の項の明示行（表記差・追加区分。判断そのもの）
--   2. 名称がマスタと完全一致（款は map の款対応を介す）
--   3. どれにも当たらない → master_* が null のまま残る
-- ⚠️ **null を黙って配らない** — 一般会計の歳出で null が出る状態は
-- tests/account_map_covers_lines.sql が止める。特別会計はマスタの対象外
-- （施行規則の備考6）なので null が正しい。
with names as (
    -- 三鷹市: 原典の名称（市が公表した文字列そのもの）
    select
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_label as kan_name,
        kou_code, kou_label as kou_name,
        moku_code, moku_label as moku_name,
        'source-csv' as name_source
    from {{ ref('core_budget_lines') }}
    where jurisdiction_code = '132047'
    union all
    select
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_label, kou_code, kou_label, moku_code, moku_label, 'source-csv'
    from {{ ref('core_revenue_lines') }}
    where jurisdiction_code = '132047'
    union all
    -- 狛江市: 決算書 PDF の見出しから解決した名称（fudoki の判断）
    select
        l.jurisdiction_code, l.fiscal_year, l.direction, l.fund_code, l.fund_label,
        l.kan_code, n.kan_name, l.kou_code, n.kou_name, l.moku_code, n.moku_name,
        -- ⚠️ 名称が無い行に出所を主張しない。PDF の無い年度（2018〜2019）は null のまま
        case when n.kan_name is not null then 'settlement-pdf' end
    from {{ ref('core_budget_lines') }} as l
    left join {{ ref('core_budget_account_names') }} as n
        using (jurisdiction_code, fiscal_year, fund_code, kan_code, kou_code, moku_code)
    where l.jurisdiction_code = '132195'
),

distinct_accounts as (
    select distinct
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_name, kou_code, kou_name, moku_code, moku_name, name_source
    from names
),

master_kou as (
    select distinct kan_code, kan_name, kou_code, kou_name from {{ ref('account_master') }}
),

kan_map as (
    select jurisdiction_code, direction, kan_code, master_kan_code, basis
    from {{ ref('account_map') }} where kou_name = '' or kou_name is null
),

kou_map as (
    select jurisdiction_code, direction, kan_code, kou_name, kind, master_kan_code, master_kou_code, basis
    from {{ ref('account_map') }} where kou_name != ''
)

select
    a.jurisdiction_code,
    a.fiscal_year,
    a.direction,
    a.fund_code,
    a.fund_label,
    a.kan_code, a.kan_name,
    a.kou_code, a.kou_name,
    a.moku_code, a.moku_name,
    a.name_source,
    -- マスタ側。一般会計の歳出だけに付く（歳入と特別会計は様式の対象外）
    km.master_kan_code,
    mk.kan_name as master_kan_name,
    coalesce(xm.master_kou_code, mc.kou_code)  as master_kou_code,
    coalesce(mc2.kou_name, mc.kou_name)        as master_kou_name,
    case
        when xm.kind is not null then xm.kind
        when mc.kou_code is not null then 'map'
    end as master_kind,
    coalesce(xm.basis, case when mc.kou_code is not null
        then '項の名称がマスタと完全一致（款は account_map の対応を介す）' end) as master_basis
from distinct_accounts as a
left join kan_map as km
    on km.jurisdiction_code = a.jurisdiction_code
    and km.direction = a.direction
    and km.kan_code = a.kan_code
    and a.fund_label = '一般会計'
left join (select distinct kan_code, kan_name from {{ ref('account_master') }}) as mk
    on mk.kan_code = km.master_kan_code
-- 2. 名称の完全一致（マスタの款の下に同名の項があるか）
left join master_kou as mc
    on mc.kan_code = km.master_kan_code and mc.kou_name = a.kou_name
-- 1. 明示の対応（表記差・追加）。あればこちらが勝つ
left join kou_map as xm
    on xm.jurisdiction_code = a.jurisdiction_code
    and xm.direction = a.direction
    and xm.kan_code = a.kan_code
    and xm.kou_name = a.kou_name
left join master_kou as mc2
    on mc2.kan_code = xm.master_kan_code and mc2.kou_code = xm.master_kou_code
