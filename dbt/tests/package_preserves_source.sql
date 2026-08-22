-- **配布する CSV そのものが原典と一致すること。**
--
-- ⚠️ 既存の検査は raw→staging（`canonical_preserves_source`）と
-- staging 内部（`code_label_reconstructs_source`）しか見ておらず、
-- **実際に配る CSV は誰も検査していなかった**。
-- package モデルが行を落とす・列を取り違える・label を NULL にしても、既存の検査は通る。
-- 配布物から `*_source` を落としてよい根拠は、ここが通ることで初めて成立する。
--
-- キーに団体・年度・予算段階・direction を含める。含めないと、
-- 内容が同じ行を別の年度へ誤配属しても検出できない。
{% set code = '132047' %}
{% set levels = var('budget_levels')[code] %}

with from_package as (
    {% for direction, lv in levels.items() %}
    select
        '{{ code }}' as jurisdiction, fiscal_year, phase_id, '{{ direction }}' as direction,
        -- ⚠️ 空のコード（階層なしのプレースホルダ）は CSV から読み戻すと NULL になる。
        -- coalesce しないと、その行だけ丸ごと NULL の cells になって突合が壊れる。
        [{% for l in lv %}coalesce({{ l }}_code, '') || coalesce({{ l }}_label, ''){% if not loop.last %}, {% endif %}{% endfor %},
         cast(source_amount as varchar)] as cells,
        count(*) as n
    from read_csv('../data/budget/datapackages/{{ code }}/{{ direction }}.csv',
                  header = true, all_varchar = false)
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

from_staging as (
    {% for direction, lv in levels.items() %}
    select
        jurisdiction_code as jurisdiction, fiscal_year, phase_id, direction,
        [{% for l in lv %}{{ l }}_source, {% endfor %}cast(source_amount as varchar)] as cells,
        count(*) as n
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    coalesce(p.jurisdiction, s.jurisdiction) as jurisdiction,
    coalesce(p.direction, s.direction)       as direction,
    coalesce(p.cells, s.cells)               as cells,
    p.n                                      as in_package,
    s.n                                      as in_staging
from from_package as p
full outer join from_staging as s
    using (jurisdiction, fiscal_year, phase_id, direction, cells)
where coalesce(p.n, 0) is distinct from coalesce(s.n, 0)
