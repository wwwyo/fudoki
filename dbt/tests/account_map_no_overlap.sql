-- **対応表のキーが年度範囲で重ならないか。** 同じ (団体, 方向, 会計, 款, 項) に
-- 年度範囲が重なる行が2つあると、join で科目行が増殖する。
-- 項のキーは名称（kou_name）とコード（kou_code）のどちらか。
select a.jurisdiction_code, a.direction, a.fund, a.kan_code,
       a.kou_name, a.kou_code, '対応行が年度範囲で重なる' as problem
from {{ ref('account_map') }} as a
join {{ ref('account_map') }} as b
    on  a.jurisdiction_code = b.jurisdiction_code
    and a.direction         = b.direction
    and coalesce(a.fund, '') = coalesce(b.fund, '')
    and a.kan_code          = b.kan_code
    and coalesce(a.kou_name, '') = coalesce(b.kou_name, '')
    and coalesce(a.kou_code, '') = coalesce(b.kou_code, '')
    and a.rowid < b.rowid
    -- 年度範囲の重なり: a の開始が b の期間内か、b の開始が a の期間内か
    and coalesce(cast(a.fiscal_year_from as integer), -9999)
            <= coalesce(cast(b.fiscal_year_to as integer), 9999)
    and coalesce(cast(b.fiscal_year_from as integer), -9999)
            <= coalesce(cast(a.fiscal_year_to as integer), 9999)
