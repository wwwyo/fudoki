-- 歳入の判断。**COFOG のディビジョンは付かない。**
-- COFOG は政府支出の機能別分類なので、歳入には分類の軸が無い。
--
-- ただし**連結の軸には歳入も参加する。** 会計間の繰出は歳出側の「繰出金」と
-- 歳入側の「他会計繰入金」の対で起きるので、片側だけ消去すると
-- 全会計を合計したときに歳入だけ二重に数えることになる。
--
-- ⚠️ **消去できるかは団体ごとに違う。**
-- 三鷹市は款・項・目に名称があるので、どの会計から受けたかを原典から読める。
-- 狛江市は款・項・目が数字コードだけで、名称を持つのは最下位階層（細節）である。
-- 一般会計の「特別会計繰入金」はどの特別会計からかが原典から読めず、
-- さらに都からの繰入金が同じ款に同居している。
-- **捏造しない**ので、狛江市は interfund_transfers.csv に宣言したものだけを消去する
-- （宣言は受け側の款項と金額を対で検算したもの。同じ款項でも宣言が無い行は残す）。
with lines as (
    select * from {{ ref('core_revenue_lines') }}
),

transfers as (
    -- 宣言した会計間移転（seeds/budget/interfund_transfers.csv）。
    -- 項・目・節のどの粒度でも書ける。`*` のキーはワイルドカード。
    select
        l.budget_line_id,
        t.counterpart_fund,
        t.basis
    from {{ ref('interfund_transfers') }} as t
    join lines as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  = '*' or t.moku_code  = l.moku_code)
        and (t.setsu_code = '*' or t.setsu_code = l.setsu_code)
        and (t.amount_yen = '*' or t.amount_yen = cast(l.amount_yen as varchar))
    where t.direction = 'revenue'
),

judged as (
    select
        l.*,
        t.counterpart_fund as declared_counterpart,
        t.basis as declared_basis,
        l.jurisdiction_code = '132047'
            and l.kan_label like '%繰入金%'
            -- ⚠️ **基金繰入金は会計間の移転ではない**（同一会計内で基金を取り崩している）。
            -- 項が「基金繰入金」のものを除かないと、消去額が歳出側と一致しなくなる。
            and l.kou_label not like '%基金繰入金%' as is_interfund
    from lines as l
    left join transfers as t using (budget_line_id)
)

select
    jurisdiction_code,
    fiscal_year,
    direction,
    budget_line_id,
    source_row,
    -- 分類の軸は歳入に存在しない。空にするのではなく、そう明示する。
    'not-applicable'                                     as cofog_status,
    ''                                                   as cofog_division,
    ''                                                   as cofog_group,
    ''                                                   as cofog_class,
    case when is_interfund or declared_counterpart is not null
         then 'eliminated' else 'retained' end           as cofog_consolidation,
    case when declared_counterpart is not null then '行'
         when is_interfund then '項'
         else '（規則なし）' end                          as cofog_decided_at_level,
    case when is_interfund then 'revenue-interfund' end  as cofog_rule_id,
    -- 出し手の会計。項が「特別会計繰入金」のときだけ目に会計名が入る
    -- （一般会計が受け皿になる唯一の対）。それ以外の受け皿は一般会計から受ける。
    case
        when declared_counterpart is not null then declared_counterpart
        when not is_interfund then null
        when kou_label = '特別会計繰入金' then regexp_replace(moku_label, '繰入金$', '')
        else '一般会計'
    end                                                  as cofog_counterpart_fund,
    case
        when declared_counterpart is not null
            then 'interfund_transfers.csv の宣言: ' || declared_basis
        when is_interfund
            then '会計間の繰入。歳出側の繰出金と対になるので、連結時に両側を消去する'
        when jurisdiction_code = '132195'
            then '歳入に COFOG の分類の軸は無い。狛江市の繰入金はどの会計から来たかを'
                 || '原典から決められないものが残るので、宣言が無い行は消去しない'
                 || '（同じ款項に一般会計と都からの繰入金が混在する。対の検算が付かない'
                 || '年度・科目は残す。例: 2019年度の下水道会計、2021年度の介護・後期）'
        else '歳入に COFOG の分類の軸は無い。連結の対象でもない'
    end                                                  as cofog_basis
from judged
