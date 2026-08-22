-- **入力が空でないこと。**
--
-- 多くの検査は「差が無いこと」を見るので、**両側が空だと全部通る。**
-- 原典が1 direction 落ちた、取得が失敗した、といったときに
-- 検査は全部緑のまま配布物だけ空になる。それを塞ぐ。
--
-- 期待する direction の集合と突き合わせるので、片側が消えても検出できる
-- （inner join だけだと消えた direction ごと比較から外れる）。
with actual as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, count(*) as rows
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

wanted as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    coalesce(w.jurisdiction, a.jurisdiction) as jurisdiction,
    coalesce(w.direction, a.direction)       as direction,
    coalesce(a.rows, 0)                      as rows
from wanted as w
full outer join actual as a using (jurisdiction, direction)
where coalesce(a.rows, 0) = 0
