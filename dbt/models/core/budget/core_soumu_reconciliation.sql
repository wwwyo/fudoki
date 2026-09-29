-- 総務省統計との突合。fudoki 側の歳出を参照データと同じ区分
-- （scope = 普通会計フレーム or 会計の canonical_fund）× マスタ款 で畳み、
-- 差分を分類付きで出す。
--
-- **比較の次元は実装前に固定したもの。**
--   団体        狛江市（決算書が執行段階の金額を持つ唯一の団体）
--   年度        収録した決算年度（今は 2023 だけ）
--   段階        fudoki 側は執行累計（決算）、参照は調査票の決算額
--   会計範囲    futsu-kaikei = 普通会計フレーム（fund_directory.sector）。
--               狛江市は特別会計がすべて公営事業会計相当なので一般会計のみ
--   単位        参照は千円、fudoki は円。突合は円で行う
--   対応        款ラベル = マスタの款名（特別会計は会計固有マスタの款名）
--
-- verdict の意味。
--   match          差 0
--   survey-reclass 調査票記入時の目的別振替差（soumu_expected_diffs に宣言）
--   unresolved     大きな差分で要因が確定していない（soumu_expected_diffs に宣言）
--   unmapped       fudoki 側がマスタに写像していない款（説明不能な差ではない）
--   no-reference   その scope の参照データが無い（駐車場・下水道など調査票が無い会計）
--   unexplained    **宣言されていない差分。** tests/soumu_reconciliation.sql が止める
with accounts as (
    select distinct
        a.jurisdiction_code, a.fiscal_year, a.fund_label, a.kan_code,
        fd.canonical_fund, fd.sector, a.master_kan_name
    from {{ ref('core_budget_accounts') }} as a
    left join {{ ref('fund_directory') }} as fd
        on fd.jurisdiction_code = a.jurisdiction_code
        and fd.fund_label = a.fund_label
    where a.direction = 'expenditure'
),

ours as (
    select
        a.jurisdiction_code,
        a.fiscal_year,
        case when a.sector = 'futsu-kaikei' then 'futsu-kaikei' else a.canonical_fund end as scope,
        a.master_kan_name as kan_label,
        sum(s.source_amount_executed) as our_yen
    -- ⚠️ **執行額は staging の列。** core の amount_yen は primary 段階
    -- （狛江市は予算計）なので執行累計はここから取る。金額の列名は
    -- budget_amounts が団体ごとに宣言するので団体別の枝になるが、
    -- 執行段階を持つのは狛江市だけなので分岐を増やさない。
    from {{ ref('stg_132195__expenditure') }} as s
    join accounts as a
        on  a.jurisdiction_code = s.jurisdiction_code
        and a.fiscal_year       = s.fiscal_year
        and a.fund_label        = s.fund_label
        and a.kan_code          = s.kan_code
    group by 1, 2, 3, 4
),

comparison as (
    select
        coalesce(o.jurisdiction_code, r.jurisdiction_code) as jurisdiction_code,
        coalesce(o.fiscal_year, cast(r.fiscal_year as integer)) as fiscal_year,
        coalesce(o.scope, r.scope)   as scope,
        coalesce(o.kan_label, r.kan_label) as kan_label,
        o.our_yen,
        cast(r.amount_thousand_yen as bigint) * 1000 as reference_yen
    from ours as o
    full outer join {{ ref('soumu_reference') }} as r
        on  r.jurisdiction_code = o.jurisdiction_code
        and cast(r.fiscal_year as integer) = o.fiscal_year
        and r.scope   = o.scope
        and r.direction = 'expenditure'
        and r.kan_label = o.kan_label
)

select
    c.jurisdiction_code,
    c.fiscal_year,
    c.scope,
    'expenditure'                                    as direction,
    c.kan_label,
    c.our_yen,
    c.reference_yen,
    coalesce(c.our_yen, 0) - coalesce(c.reference_yen, 0) as diff_yen,
    case
        when rs.scope is null then 'no-reference'
        when c.kan_label is null then 'unmapped'
        -- 参照値は千円。円未満の差は参照の精度を超えるので一致とみなす
        when abs(coalesce(c.our_yen, 0) - coalesce(c.reference_yen, 0)) < 1000 then 'match'
        when ed.klass is not null then ed.klass
        else 'unexplained'
    end                                              as verdict,
    ed.note                                          as diff_note
from comparison as c
left join (
    select distinct jurisdiction_code, fiscal_year, scope
    from {{ ref('soumu_reference') }}
) as rs
    on  rs.jurisdiction_code = c.jurisdiction_code
    and cast(rs.fiscal_year as integer) = c.fiscal_year
    and rs.scope = c.scope
left join {{ ref('soumu_expected_diffs') }} as ed
    on  ed.jurisdiction_code = c.jurisdiction_code
    and cast(ed.fiscal_year as integer) = c.fiscal_year
    and ed.scope = c.scope
    and ed.direction = 'expenditure'
    and ed.kan_label = c.kan_label
