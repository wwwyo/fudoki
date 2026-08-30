-- 科目（款・項・目）の一覧と、法定マスタへの解決。**団体をまたいで同じ形。**
--
-- 粒度は**科目**（団体 × 年度 × 会計 × 款・項・目）である。予算の行の同一性には
-- 所属や予算区分も要るが、それは行のカタログではなく科目のカタログなので含めない
-- （同じ科目が複数の所属に現れても、科目としての名称と法定対応は1つ）。
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
    -- 原典の行がそのまま名称を持つ団体。**写経しない** — 出所の語彙は
    -- `budget_account_name_sources` が団体ごとに宣言する。
    -- ⚠️ 以前ここは団体ごとに同じ4つの select を写していた（3団体で12個）。
    -- 4団体目を足すときに同じ形をもう2つ増やすことになったので宣言へ寄せた。
    {%- for code, name_source in var('budget_account_name_sources').items() %}
    select
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_label as kan_name,
        kou_code, kou_label as kou_name,
        moku_code, moku_label as moku_name,
        '{{ name_source }}' as name_source
    from {{ ref('core_budget_lines') }}
    where jurisdiction_code = '{{ code }}'
    union all
    select
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_label, kou_code, kou_label, moku_code, moku_label, '{{ name_source }}'
    from {{ ref('core_revenue_lines') }}
    where jurisdiction_code = '{{ code }}'
    union all
    {%- endfor %}
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
    union all
    -- 狛江市の歳入。名称は歳入事項別明細から解決した 2023年度だけに付く。
    -- ⚠️ 2020〜2022 の歳入 PDF は文字がアウトライン化されておりテキスト抽出が成立しない。
    -- OCR は誤読が多く名称の全量には使えなかった（実測。詳細は jurisdictions/132195.md）。
    -- 名称の無い年度は null で正直に残す（款の master 対応は account_map が 2020年度以降に効かせる）。
    select
        l.jurisdiction_code, l.fiscal_year, l.direction, l.fund_code, l.fund_label,
        l.kan_code, n.kan_name, l.kou_code, n.kou_name, l.moku_code, n.moku_name,
        case when n.kan_name is not null then 'settlement-pdf' end
    from {{ ref('core_revenue_lines') }} as l
    left join {{ ref('stg_132195__revenue_accounts') }} as n
        -- ⚠️ **名称に使うのはテキスト経路だけ。** OCR 経路（2020〜2022）は誤読が多く、
        -- 壊れた名称と巻き戻った款コードが実際に流れ込んだ。raw には残すが名称には使わない
        on n.mode = 'text'
        and n.fiscal_year = l.fiscal_year
        and l.fund_label = '一般会計'
        and n.kan_code = l.kan_code and n.kou_code = l.kou_code and n.moku_code = l.moku_code
    where l.jurisdiction_code = '132195'
),

distinct_accounts as (
    select distinct
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_name, kou_code, kou_name, moku_code, moku_name, name_source
    from names
),

-- ⚠️ **direction を落とさない。** 歳入の款6（法人事業税交付金）と歳出の款6（農林水産業費）は
-- 同じコードで別物。direction 抜きで join すると両方に当たる。
master_kou as (
    select distinct direction, kan_code, kan_name, kou_code, kou_name from {{ ref('account_master') }}
),

kan_map as (
    select jurisdiction_code, direction, kan_code, fiscal_year_from, kind, master_kan_code, basis
    from {{ ref('account_map') }} where kou_name = '' or kou_name is null
),

kou_map as (
    select jurisdiction_code, direction, kan_code, kou_name, fiscal_year_from,
           kind, master_kan_code, master_kou_code, basis
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
    -- マスタ側。一般会計の歳入・歳出に付く（特別会計は様式の対象外 = 備考5・6）。
    -- 名称の無い団体 × 方向（狛江市の歳入）は対応を保留し、null のまま残す
    km.master_kan_code,
    mk.kan_name as master_kan_name,
    coalesce(xm.master_kou_code, mc.kou_code)  as master_kou_code,
    coalesce(mc2.kou_name, mc.kou_name)        as master_kou_name,
    case
        when xm.kind is not null then xm.kind
        when mc.kou_code is not null then 'map'
        -- **款そのものに対応先が無い2つの型。** どちらも「突き合わせた結果ここには無い」
        -- という判断で、突き合わせていない状態（null）とは別物。
        --   historical  旧法定区分（例: 自動車取得税交付金）。現行様式から削除された
        --   addition    様式の備考が条件付きで認める款（例: ゴルフ場利用税交付金は
        --               歳入の備考2がゴルフ場所在市町村に挿入を認めている）
        when km.kind in ('historical', 'addition') then km.kind
    end as master_kind,
    coalesce(xm.basis, case when mc.kou_code is not null
        then '項の名称がマスタと完全一致（款は account_map の対応を介す）'
        when km.kind in ('historical', 'addition') then km.basis end) as master_basis
from distinct_accounts as a
left join kan_map as km
    on km.jurisdiction_code = a.jurisdiction_code
    and km.direction = a.direction
    and km.kan_code = a.kan_code
    and a.fund_label = '一般会計'
    -- ⚠️ 款コードの意味が年度で変わる団体がある（狛江市の歳入は 2019/2020 の境界で
    -- 款の新設により繰り下がった）。対応はそれが確認できた年度からしか効かせない
    and (nullif(km.fiscal_year_from, '') is null or a.fiscal_year >= cast(km.fiscal_year_from as integer))
left join (select distinct direction, kan_code, kan_name from {{ ref('account_master') }}) as mk
    on mk.direction = a.direction and mk.kan_code = km.master_kan_code
-- 2. 名称の完全一致（マスタの款の下に同名の項があるか）
left join master_kou as mc
    on mc.direction = a.direction and mc.kan_code = km.master_kan_code and mc.kou_name = a.kou_name
-- 1. 明示の対応（表記差・追加）。あればこちらが勝つ
left join kou_map as xm
    on xm.jurisdiction_code = a.jurisdiction_code
    and xm.direction = a.direction
    and xm.kan_code = a.kan_code
    and xm.kou_name = a.kou_name
    -- ⚠️ 款と同じ年度条件。項だけ無条件だと、款体系が違う年度に項の対応が誤適用される
    and (nullif(xm.fiscal_year_from, '') is null or a.fiscal_year >= cast(xm.fiscal_year_from as integer))
left join master_kou as mc2
    on mc2.direction = a.direction and mc2.kan_code = xm.master_kan_code and mc2.kou_code = xm.master_kou_code
