-- **対応表のキーが年度範囲で重ならないか。** 同じ (団体, 方向, 会計, 款, 項) に
-- 年度範囲が重なる行が2つあると、join で科目行が増殖する。
-- ⚠️ 衝突はモデルが実際に効かせるキーで見る — fund の空は「一般会計」と
-- 同じ意味（モデルが coalesce する）なのでここでも正規化する。項の衝突は
-- 名称・コードのどちらかが一致すれば起きる（モデルは OR で当てる）。
select a.jurisdiction_code, a.direction, a.fund, a.kan_code,
       a.kou_name, a.kou_code, '対応行が年度範囲で重なる' as problem
from {{ ref('account_map') }} as a
join {{ ref('account_map') }} as b
    on  a.jurisdiction_code = b.jurisdiction_code
    and a.direction         = b.direction
    and coalesce(a.fund, '一般会計') = coalesce(b.fund, '一般会計')
    and a.kan_code          = b.kan_code
    -- 衝突の検査は「当たるキー」が共通するとき。項なし行（款の対応）同士は
    -- 両方のキーが空で一致として扱い、項行は名前 or コードのキーが同値のとき
    and (coalesce(a.kou_name, '') = coalesce(b.kou_name, '')
         and coalesce(a.kou_code, '') = coalesce(b.kou_code, '')
         or nullif(a.kou_name, '') is not null and a.kou_name = b.kou_name
         or nullif(a.kou_code, '') is not null and a.kou_code = b.kou_code)
    and a.rowid < b.rowid
    -- 年度範囲の重なり: a の開始が b の期間内か、b の開始が a の期間内か
    and coalesce(cast(a.fiscal_year_from as integer), -9999)
            <= coalesce(cast(b.fiscal_year_to as integer), 9999)
    and coalesce(cast(b.fiscal_year_from as integer), -9999)
            <= coalesce(cast(a.fiscal_year_to as integer), 9999)
