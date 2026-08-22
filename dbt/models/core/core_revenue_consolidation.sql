-- 歳入の判断。**COFOG のディビジョンは付かない。**
-- COFOG は政府支出の機能別分類なので、歳入には分類の軸が無い。
--
-- ただし**連結の軸には歳入も参加する。** 会計間の繰出は歳出側の「繰出金」と
-- 歳入側の「他会計繰入金」の対で起きるので、片側だけ消去すると
-- 全会計を合計したときに歳入だけ二重に数えることになる。
--
-- ⚠️ **基金繰入金は会計間の移転ではない**（同一会計内で基金を取り崩している）。
-- 項が「基金繰入金」のものを除かないと、消去額が歳出側と一致しなくなる。
with lines as (
    select * from {{ ref('stg_132047__revenue') }}
),

judged as (
    select
        *,
        kan_label like '%繰入金%' and kou_label not like '%基金繰入金%' as is_interfund
    from lines
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
    case when is_interfund then 'eliminated' else 'retained' end as cofog_consolidation,
    case when is_interfund then '項' else '（規則なし）' end      as cofog_decided_at_level,
    case when is_interfund then 'revenue-interfund' end  as cofog_rule_id,
    -- 出し手の会計。項が「特別会計繰入金」のときだけ目に会計名が入る
    -- （一般会計が受け皿になる唯一の対）。それ以外の受け皿は一般会計から受ける。
    case
        when not is_interfund then null
        when kou_label = '特別会計繰入金' then regexp_replace(moku_label, '繰入金$', '')
        else '一般会計'
    end                                                  as cofog_counterpart_fund,
    case
        when is_interfund
            then '会計間の繰入。歳出側の繰出金と対になるので、連結時に両側を消去する'
        else '歳入に COFOG の分類の軸は無い。連結の対象でもない'
    end                                                  as cofog_basis
from judged
