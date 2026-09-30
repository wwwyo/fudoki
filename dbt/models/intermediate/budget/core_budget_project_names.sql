-- **事業名を大事業コードへ対応づける。fudoki の判断。**
--
-- 原典の CSV は款・項・目・大事業を数字コードでしか持たず、名称の列が無い。
-- 名称は決算資料 PDF にあるが、**PDF は大事業コードを書いていない**（款-項-目 と事業名だけ）。
-- したがってコードでは結合できず、**同じ目の中で金額が一致するもの**を対応づけることになる。
-- 「この事業名はこの大事業コードのことだ」と決めるのは自治体が言っていないことなので、
-- staging には置けない。配布物も派生の側に出す。
--
-- ## 実測して分かった、結合を成立させるのに要ったこと
--
-- 1. **PDF は主管課ごとに行を分ける。** 同じ大事業でも所属が違えば別行になる
--    （2022 の 2-1-1「一般事務費」は5つの所属に割れ、合計だけが大事業2と一致した）。
--    だから候補には大事業の合計と**所属別の小計の両方**を入れる。
-- 2. **千円への丸めが1ずれる。** PDF の丸め規則を再現できていない（款別で11款中10款は
--    合計の丸めと一致したが、衛生費だけ1千円ずれた）。floor / round / ceil を候補にして吸収する。
-- 3. **同額が並ぶ。** 同じ目に同額の大事業が2つあることがある。金額だけでは決まらないので、
--    **出現順**で割り当てる（PDF も CSV も大事業コードの順に並んでいる）。
--
-- ⚠️ **金額が 0 の事業には名前が付かない。** 0 は同じ目に何件も現れて区別できない。
-- 実測で 2020〜2023 の各年度に 15〜30 件ある。捨てずに「名前なし」として残す（原則6）。
with pdf as (
    -- ⚠️ **突合できない目からは名前を採らない。** 抽出漏れがあると目の合計に届かず、
    -- 残った行だけで金額を突き合わせると**別の事業の名前が付く**。
    -- 落とすのではなく境界に理由を持たせるための足切り（年度あたり 1〜4 目）。
    select * from {{ ref('stg_132195__project_names') }} where moku_reconciled
),

-- 候補。大事業の合計と、所属別の小計の両方を、丸めの揺れごと持つ
csv_amounts as (
    select fiscal_year, kan_code, kou_code, moku_code, daijigyo_code,
           sum(source_amount_executed) as yen, 0 as level_priority
    from {{ ref('stg_132195__expenditure') }}
    where fund_code = '1'          -- PDF の事項別明細は一般会計だけ
    group by 1, 2, 3, 4, 5

    union all

    -- 所属別の小計。**合計より後に置く**（下の order by で優先順位になる）
    select fiscal_year, kan_code, kou_code, moku_code, daijigyo_code,
           sum(source_amount_executed), 1
    from {{ ref('stg_132195__expenditure') }}
    where fund_code = '1'
    group by 1, 2, 3, 4, 5, org_code
),

-- ⚠️ **どの丸めで当たったかを残す。** 配布物に出して、利用者が対応を疑ったときに
-- 「完全一致で当てたのか、丸めの揺れを吸収して当てたのか」を区別できるようにする。
candidates as (
    -- ⚠️ **`min(method)` は辞書順**で ceil < floor < round になり、優先度と無関係に ceil を返す。
    -- 優先度が最小の候補に**対応する**方法を取る。
    select fiscal_year, kan_code, kou_code, moku_code, daijigyo_code, thousand,
           arg_min(method, priority) as method,
           min(priority) as priority,
           arg_min(level_priority, priority) as level_priority
    from (
        select fiscal_year, kan_code, kou_code, moku_code, daijigyo_code,
               unnest([round(yen / 1000.0)::bigint, floor(yen / 1000.0)::bigint, ceil(yen / 1000.0)::bigint]) as thousand,
               unnest(['round', 'floor', 'ceil']) as method,
               -- ⚠️ **候補には強さの差がある。** 素直に丸めて大事業の合計と一致するものが
               -- 一番強く、丸めの揺れ（floor / ceil）や所属別の小計は「拾えなかったときの受け皿」。
               -- 差を付けずに大事業コード順で並べると、**弱い候補が強い候補より先に順位を取り、
               -- 正しい事業から名前を奪う**（実測: 2021 の 10-1-3 で「いじめ問題等対策推進」が
               -- 所属別小計の floor 候補に枠を取られ、配布物から消えていた）。
               unnest([0, 1, 1]) + level_priority * 2 as priority,
               level_priority
        from csv_amounts
    )
    group by 1, 2, 3, 4, 5, 6
),

-- ⚠️ **順位は join の前に決める。** join の後で row_number() を取ると、
-- 候補が複数ある PDF 行が候補の数だけ複製され、その複製に別々の順位が振られる。
-- 順位付けの順序が実行ごとに変わるので、**同じ入力から違う配布物が出る**
-- （CI の「再生成しても commit 済みと一致するか」が実際に落ちた）。
pdf_ranked as (
    select *,
        row_number() over (
            partition by fiscal_year, kan_code, kou_code, moku_code, amount_thousand_yen
            order by ordinal
        ) as rank_in_amount
    from pdf
),

csv_ranked as (
    select *,
        row_number() over (
            partition by fiscal_year, kan_code, kou_code, moku_code, thousand
            order by priority, cast(daijigyo_code as integer)
        ) as rank_in_amount
    from candidates
),

-- 金額と、同額の中での出現順が揃った組だけを採る
matched as (
    select
        p.fiscal_year, p.kan_code, p.kou_code, p.moku_code,
        p.jurisdiction_code,
        p.ordinal, p.project_name, p.amount_thousand_yen, c.daijigyo_code,
        c.method as match_method,
        -- ⚠️ **弱い対応づけを見えるようにする。** 大事業の合計と一致したのか、
        -- 所属別の小計の一部と一致しただけなのかで、確からしさがまったく違う
        -- （1,000円の小計で 1,480万円の大事業に名前を付けている行が実在した）。
        case when c.level_priority = 0 then 'total' else 'org_subtotal' end as match_basis
    from pdf_ranked as p
    inner join csv_ranked as c
        on  c.fiscal_year = p.fiscal_year
        and c.kan_code = p.kan_code and c.kou_code = p.kou_code and c.moku_code = p.moku_code
        and c.thousand = p.amount_thousand_yen
        and c.rank_in_amount = p.rank_in_amount
),

-- ⚠️ **1つの大事業に複数の PDF 行が当たりうる**（所属別の小計と合計が同額のとき）。
-- 先に出たものを採る。**並びを完全に決める**ため ordinal まで指定する。
assigned as (
    select *,
        row_number() over (
            partition by fiscal_year, kan_code, kou_code, moku_code, daijigyo_code
            order by ordinal, project_name, match_method
        ) as dup,
        -- ⚠️ **黙って捨てない。** 同じ大事業へ複数の PDF 行が当たったことを数として残す。
        -- 1 より大きければ、その対応づけは金額だけでは決まっていない。
        count(*) over (
            partition by fiscal_year, kan_code, kou_code, moku_code, daijigyo_code
        ) as candidate_count
    from matched
)

select
    -- ⚠️ **団体コードを直書きしない。** partition から来たものをそのまま通す。
    -- 直書きすると、取得元と食い違ったとき派生が黙って別の団体に帰属する。
    jurisdiction_code,
    fiscal_year,
    -- ⚠️ **会計を明示する。** PDF の事項別明細は一般会計だけなので、この対応づけも一般会計に閉じている。
    -- 会計を落とすと、同じ (年度, 款, 項, 目, 大事業) を持つ特別会計の行に
    -- 一般会計の事業名が付く（実測で 199 件が誤って付いていた）。
    '1'           as fund_code,
    kan_code,
    kou_code,
    moku_code,
    daijigyo_code,
    project_name,
    -- 対応づけの根拠。**判断の中身を読めるようにする**（COFOG を規則表で配るのと同じ考え）。
    amount_thousand_yen as matched_thousand_yen,
    -- round で当たったか、丸めの揺れ（floor / ceil）を吸収して当たったか
    match_method,
    match_basis,
    -- 1 より大きければ、金額だけでは決まらず出現順で決めた
    candidate_count,
    ordinal             as pdf_ordinal
from assigned
where dup = 1
