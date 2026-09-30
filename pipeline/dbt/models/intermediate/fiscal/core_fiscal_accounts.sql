-- 科目（款・項・目）の一覧と、法定マスタへの解決。**団体をまたいで同じ形。**
--
-- 粒度は**科目**（団体 × 年度 × 会計 × 款・項・目）である。予算の行の同一性には
-- 所属や予算区分も要るが、それは行のカタログではなく科目のカタログなので含めない
-- （同じ科目が複数の所属に現れても、科目としての名称と法定対応は1つ）。
--
-- 名称の出所は団体で違う。三鷹市は原典 CSV の各行に名称があり、狛江市は
-- 原典に無いので決算書 PDF の見出しから解決した（core_fiscal_account_names）。
-- どちらも (団体, 年度, 会計, 款, 項, 目) → 名称という同じ形へ畳み、
-- **どこから来た名称かを name_source で区別する**（事実と判断を列で見分けられるように）。
--
-- canonical_fund は会計の名寄せ（fund_directory）。同じ制度を担う会計は
-- 団体ごとに名前が違う（「国民健康保険事業特別会計」「国民健康保険特別会計」）ので、
-- 比較は fund_label ではなく canonical_fund で行う。
--
-- マスタへの解決は3段で当てる。
--   1. account_map の項の明示行（表記差・追加区分。判断そのもの）
--   2. 名称がマスタと完全一致（款は map の款対応を介す）
--   3. どれにも当たらない → master_* が null のまま残る
-- ⚠️ **null を黙って配らない** — 一般会計の歳出で null が出る状態は
-- tests/account_map_covers_lines.sql が止める。
--
-- ⚠️ **どのマスタに当てるかは会計で決まる。** 一般会計は地方自治法施行規則
-- 別記の区分（account_master）、法定の特別会計（国民健康保険・介護保険・
-- 後期高齢者医療）は会計ごとの調査票の勘定科目（special_account_master）に当てる。
-- 特別会計の款名が一般会計の款名と同じでも（例: 総務費）、一般会計のマスタへは
-- 当てない — 会計固有の体系であり、同名は同じ区分を意味しない。
-- 介護サービス事業は 64 表の勘定科目、駐車場・下水道などの収益事業型は
-- 50 表・64 表に共通する勘定構造を canonical な比較軸として写す（special_account_master）。
with names as (
    -- 原典の行がそのまま名称を持つ団体。**写経しない** — 出所の語彙は
    -- `fiscal_account_name_sources` が団体ごとに宣言する。
    -- ⚠️ 以前ここは団体ごとに同じ4つの select を写していた（3団体で12個）。
    -- 4団体目を足すときに同じ形をもう2つ増やすことになったので宣言へ寄せた。
    {%- for code, name_source in var('fiscal_account_name_sources').items() %}
    select
        jurisdiction_code, fiscal_year, direction, fund_code, fund_label,
        kan_code, kan_label as kan_name,
        kou_code, kou_label as kou_name,
        moku_code, moku_label as moku_name,
        '{{ name_source }}' as name_source
    from {{ ref('core_fiscal_lines') }}
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
    from {{ ref('core_fiscal_lines') }} as l
    left join {{ ref('core_fiscal_account_names') }} as n
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

accounts as (
    select a.*, fd.canonical_fund
    from distinct_accounts as a
    left join {{ ref('fund_directory') }} as fd
        on fd.jurisdiction_code = a.jurisdiction_code and fd.fund_label = a.fund_label
),

-- 款のマスタ。一般会計は地方自治法施行規則 別記、法定の特別会計は
-- 会計ごとの調査票の勘定科目。canonical_fund で突き分けるので
-- 特別会計の款が一般会計の区分に誤って写ることはない。
master_kan as (
    select '一般会計' as canonical_fund, direction, kan_code, kan_name
    from (select distinct direction, kan_code, kan_name from {{ ref('account_master') }})
    union all
    -- ⚠️ kou_code が入る行は項の定義。款のマスタに混ぜると、款の join が
    -- 項行のぶんだけ行を増殖させる
    select canonical_fund, direction, kan_code, kan_name
    from {{ ref('special_account_master') }} where kou_code is null
),

-- ⚠️ **direction を落とさない。** 歳入の款6（法人事業税交付金）と歳出の款6（農林水産業費）は
-- 同じコードで別物。direction 抜きで join すると両方に当たる。
master_kou as (
    -- ⚠️ distinct は落とさない。account_master は目の粒度で、項の行は重複する
    select '一般会計' as canonical_fund, direction, kan_code, kan_name, kou_code, kou_name
    from (select distinct direction, kan_code, kan_name, kou_code, kou_name from {{ ref('account_master') }})
    union all
    -- 特別会計の項マスタ。調査票の内訳列と帳簿で共通する項から作ってある。
    -- kou_code が空の行は款の定義なので項には入れない
    select canonical_fund, direction, kan_code, kan_name, kou_code, kou_name
    from {{ ref('special_account_master') }} where kou_code is not null
),

kan_map as (
    select jurisdiction_code, direction, fund, kan_code, fiscal_year_from, fiscal_year_to,
           kind, master_kan_code, basis
    from {{ ref('account_map') }}
    where coalesce(kou_name, '') = '' and nullif(kou_code, '') is null
),

kou_map as (
    -- 項の対応は名称（項名がある団体）か項コード（名称が無い団体）のどちらかで書く
    select jurisdiction_code, direction, fund, kan_code, kou_name, kou_code, fiscal_year_from, fiscal_year_to,
           kind, master_kan_code, master_kou_code, basis
    from {{ ref('account_map') }}
    where coalesce(kou_name, '') != '' or nullif(kou_code, '') is not null
)

select
    a.jurisdiction_code,
    a.fiscal_year,
    a.direction,
    a.fund_code,
    a.fund_label,
    a.canonical_fund,
    a.kan_code, a.kan_name,
    a.kou_code, a.kou_name,
    a.moku_code, a.moku_name,
    a.name_source,
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
        -- 特別会計の款対応はすべて明示行なので、当たれば 'map'
        when km.master_kan_code is not null then 'map'
    end as master_kind,
    coalesce(xm.basis, case when mc.kou_code is not null
        then '項の名称がマスタと完全一致（款は account_map の対応を介す）'
        when km.kind in ('historical', 'addition') then km.basis
        when km.master_kan_code is not null then km.basis end) as master_basis
from accounts as a
left join kan_map as km
    on km.jurisdiction_code = a.jurisdiction_code
    and km.direction = a.direction
    and km.kan_code = a.kan_code
    -- ⚠️ **fund 列が空の行は一般会計だけに効く。** 特別会計への対応は
    -- fund に canonical_fund を書いた行だけが当たる。空を「全会計に効く」と
    -- 読むと一般会計用の行が特別会計にも当たってしまう（同名款の誤写像）
    and coalesce(km.fund, '一般会計') = a.canonical_fund
    -- ⚠️ 款コードの意味が年度で変わる団体がある（狛江市の歳入は 2019/2020 の境界で
    -- 款の新設により繰り下がった）。対応はそれが確認できた年度にだけ効かせる
    and (nullif(km.fiscal_year_from, '') is null or a.fiscal_year >= cast(km.fiscal_year_from as integer))
    and (nullif(km.fiscal_year_to, '')   is null or a.fiscal_year <= cast(km.fiscal_year_to   as integer))
left join master_kan as mk
    on mk.canonical_fund = a.canonical_fund
    and mk.direction = a.direction and mk.kan_code = km.master_kan_code
-- 2. 名称の完全一致（一般会計のマスタの款の下に同名の項があるか）
left join master_kou as mc
    on a.canonical_fund = '一般会計'
    -- ⚠️ master_kou は特別会計の項も持つ。canonical_fund を落とすと
    -- 一般会計の項が特別会計マスタの同名項にも当たって行が増殖する
    and mc.canonical_fund = '一般会計'
    and mc.direction = a.direction and mc.kan_code = km.master_kan_code and mc.kou_name = a.kou_name
-- 1. 明示の対応（表記差・追加）。あればこちらが勝つ
left join kou_map as xm
    on xm.jurisdiction_code = a.jurisdiction_code
    and xm.direction = a.direction
    and xm.kan_code = a.kan_code
    -- 項名がある団体は名称で、無い団体は項コードで当てる。
    -- ⚠️ コード照合は対象行の項名が空のときだけ効かせる — 項名がある行まで
    -- コードで当たると、同名でない別構造の項へ誤写像する経路ができる
    and ((nullif(xm.kou_name, '') is not null and xm.kou_name = a.kou_name)
         or (nullif(xm.kou_code, '') is not null and xm.kou_code = a.kou_code
             and nullif(a.kou_name, '') is null))
    and coalesce(xm.fund, '一般会計') = a.canonical_fund
    -- ⚠️ 款と同じ年度条件。項だけ無条件だと、款体系が違う年度に項の対応が誤適用される
    and (nullif(xm.fiscal_year_from, '') is null or a.fiscal_year >= cast(xm.fiscal_year_from as integer))
    and (nullif(xm.fiscal_year_to, '')   is null or a.fiscal_year <= cast(xm.fiscal_year_to   as integer))
left join master_kou as mc2
    -- ⚠️ canonical_fund を落とすと、特別会計の対応が一般会計のマスタの
    -- 同じ款コードの項に当たる
    on mc2.canonical_fund = a.canonical_fund
    and mc2.direction = a.direction and mc2.kan_code = xm.master_kan_code and mc2.kou_code = xm.master_kou_code
