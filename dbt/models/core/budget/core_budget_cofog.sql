-- **ここから先が fudoki の判断。** 自治体が言っていないことを付け加える段。
--
-- 状態は2つの軸に分ける。分類の軸（割当済み / 分類不能 / 対象外）と
-- 連結の軸（保持 / 消去）は問いが違う。1つの排他的な状態に畳むと、
-- **分類できなかったもの**と**そもそも分類の対象でないもの**が混ざって集計が壊れる。
-- 公債費の元金償還は「分類できない」のではなく「対象外」である。
--
-- 規則は上から順に見て最初に当たったものを採る（具体的な規則ほど priority が小さい）。
-- 当たらなかった行は捨てず「（規則なし）」として分類不能に落とす（パーサ設計の原則6）。
-- 捨てた瞬間、下流にはその金額が存在しなかったことしか伝わらない。
-- ⚠️ **団体ごとの staging を直接参照しない。** 参照すると団体を足すたびにここが増え、
-- 足し忘れが黙って派生から落ちる。団体の union は core_budget_lines が1箇所で持ち、
-- 足し忘れは tests/budget_core_covers_all_staging.sql が落とす。
with lines as (
    -- ⚠️ **科目の名称が原典に無い団体は、別の資料から解決した名称で当てる。**
    -- 原典の名称が先で、無いときだけ PDF から解決したものを使う（`coalesce`）。
    -- 名称の出所は**規則の `basis` に書く**（行に複製しない。根拠は規則ごとに1つ）。
    select
        l.* exclude (kan_label, kou_label, moku_label),
        coalesce(nullif(l.kan_label, ''),  n.kan_name,  '') as kan_label,
        coalesce(nullif(l.kou_label, ''),  n.kou_name,  '') as kou_label,
        coalesce(nullif(l.moku_label, ''), n.moku_name, '') as moku_label,
    from {{ ref('core_budget_lines') }} as l
    left join {{ ref('core_budget_account_names') }} as n
        on  n.jurisdiction_code = l.jurisdiction_code
        and n.fiscal_year       = l.fiscal_year
        and n.fund_code         = l.fund_code
        and n.kan_code          = l.kan_code
        and n.kou_code          = l.kou_code
        and n.moku_code         = l.moku_code
),

rules as (
    select
        priority,
        rule_id,
        coalesce(applies_to, '')       as applies_to,
        coalesce(match_fund, '')       as match_fund,
        coalesce(match_kan, '')        as match_kan,
        coalesce(match_kou, '')        as match_kou,
        coalesce(match_moku, '')       as match_moku,
        coalesce(moku_mode, 'eq')      as moku_mode,
        -- ⚠️ **コードでの照合。** 狛江市は款・項・目に名称の列が原典に無く、
        -- 名称でしか当たらない規則では1行も分類できない。名称を捏造せず、
        -- コードで当てて根拠（basis）に何の款かとその出所を書く。
        coalesce(match_kan_code, '')   as match_kan_code,
        coalesce(match_setsu, '')      as match_setsu,
        status,
        -- ⚠️ **割当は1列（cofog_code）で持つ。** division / group / class を
        -- 別々に宣言すると同じ事実が3箇所に分かれ、粒度を下げたときに片方だけ古くなる。
        -- 分解は下の select が導出する（`04.5.1` → division 04 / group 04.5 / class 04.5.1）。
        coalesce(cofog_code, '')       as cofog_code,
        consolidation,
        decided_at_level,
        coalesce(counterpart_fund, '') as counterpart_fund,
        basis
    from {{ ref('cofog_rules') }}
),

transfers as (
    -- 宣言した会計間移転（seeds/budget/interfund_transfers.csv）。
    -- 受け皿の会計が分かる行だけを行・項・款の粒度で宣言してあり、
    -- 宣言したものは規則の結果より先に効く。
    -- amount_yen を書いた行は**額まで一致しないと当たらない**（同じ科目に
    -- 複数の受け皿があるとき、受け皿を行単位で確定するため）。
    select
        l.budget_line_id,
        t.counterpart_fund,
        t.basis,
        fr.cofog_code as counterpart_cofog_code
    from {{ ref('interfund_transfers') }} as t
    join lines as l
        on  l.jurisdiction_code = t.jurisdiction_code
        and l.fiscal_year       = cast(t.fiscal_year as integer)
        and l.fund_label        = t.fund_label
        and l.kan_code          = t.kan_code
        and l.kou_code          = t.kou_code
        and (t.moku_code  is null or t.moku_code  = l.moku_code)
        and (t.setsu_code is null or t.setsu_code = l.setsu_code)
        and (t.amount_yen is null or cast(t.amount_yen as bigint) = l.amount_yen)
    left join rules as fr
        -- 受け皿の会計が決まる行は、受け皿側の会計規則の COFOG を借りる
        -- （一般会計へ戻す繰出はどの機能にも割り当てられないので空のまま）。
        on (fr.applies_to = '' or fr.applies_to = l.jurisdiction_code)
        and fr.match_fund = t.counterpart_fund
        and fr.decided_at_level = '会計'
    where t.direction = 'expenditure'
),

matched as (
    select
        l.budget_line_id,
        r.*,
        -- ⚠️ **source_row で束ねない。** 原典の行番号は1リソース内でしか一意でなく、
        -- 2年度目を足した時点で年度をまたいで衝突する。budget_line_id は
        -- 団体・年度・direction・段階を含むので、増やしても衝突しない。
        row_number() over (partition by l.budget_line_id order by r.priority) as rn
    from lines as l
    inner join rules as r
        -- 団体スコープ。空は法定語彙にだけ当たる規則で、どの団体にも効く。
        -- スコープを付け忘れると他団体の同名でない科目に当たらないまま素通りし、
        -- 壊れずに大量が分類不能へ落ちる（検査は通るので気づけない）。
        on (r.applies_to = '' or r.applies_to = l.jurisdiction_code)
        and (r.match_fund = '' or l.fund_label = r.match_fund)
        and (r.match_kan = '' or l.kan_label = r.match_kan)
        and (r.match_kan_code = '' or l.kan_code = r.match_kan_code)
        and (r.match_kou = '' or list_contains(str_split(r.match_kou, '|'), l.kou_label))
        and (
            r.match_moku = ''
            or case
                when r.moku_mode = 'contains' then l.moku_label like '%' || r.match_moku || '%'
                else list_contains(str_split(r.match_moku, '|'), l.moku_label)
            end
        )
        and (r.match_setsu = '' or l.setsu_label = r.match_setsu)
)

select
    l.jurisdiction_code,
    l.fiscal_year,
    l.direction,
    l.budget_line_id,
    l.source_row,
    case
        -- 宣言した会計間移転が当たった行。受け皿が一般会計の繰出は
        -- どの機能にも割り当てられない（対象外）。特別会計への繰出は
        -- 受け皿の会計の機能を借りる。
        when t.budget_line_id is not null
            then case when t.counterpart_fund = '一般会計' then 'out-of-scope' else 'assigned' end
        else coalesce(m.status, 'unclassifiable')
    end                                             as cofog_status,
    -- COFOG の階層。**規則が言った粒度までしか埋めない。**
    -- 款の名称だけで決まる規則は division 止まりで、group / class は空になる。
    -- 「分からない」を空で正直に出す（原則6）。
    -- ⚠️ **NULL を先に潰す。** 規則に当たらなかった行は m.* が NULL で、
    -- split_part(NULL) が NULL を返すことに頼ると、空文字で揃えるという意図が
    -- SQL の方言差に委ねられる。列ごとに coalesce を書くのではなく1度だけ潰す。
    split_part(coalesce(e.code, ''), '.', 1)                              as cofog_division,
    case when coalesce(e.code, '') like '%.%'
         then split_part(e.code, '.', 1) || '.' || split_part(e.code, '.', 2)
         else '' end                                                       as cofog_group,
    case when regexp_full_match(coalesce(e.code, ''), '\d+\.\d+\.\d+')
         then e.code else '' end                                           as cofog_class,
    case when t.budget_line_id is not null then 'eliminated'
         else coalesce(m.consolidation, 'retained') end                    as cofog_consolidation,
    case when t.budget_line_id is not null then '行'
         else coalesce(m.decided_at_level, '（規則なし）') end              as cofog_decided_at_level,
    -- 宣言ベースの行は規則表に当たる規則が無い。根拠は cofog_basis が持つ
    case when t.budget_line_id is not null then null else m.rule_id end    as cofog_rule_id,
    case when t.budget_line_id is not null then t.counterpart_fund
         else nullif(coalesce(m.counterpart_fund, ''), '') end             as cofog_counterpart_fund,
    case when t.budget_line_id is not null
         then 'interfund_transfers.csv の宣言: ' || t.basis
         else coalesce(m.basis, 'どの規則にも当たらなかった。捨てずに分類不能として残す')
    end                                             as cofog_basis
from lines as l
left join matched as m
    on l.budget_line_id = m.budget_line_id and m.rn = 1
left join transfers as t
    on t.budget_line_id = l.budget_line_id
cross join lateral (
    -- 宣言が当たった行は受け皿の会計だけが COFOG を決める
    -- （一般会計へ戻す繰出は機能が決まらないので空）
    select case when t.budget_line_id is not null
                then t.counterpart_cofog_code
                else m.cofog_code end as code
) as e
