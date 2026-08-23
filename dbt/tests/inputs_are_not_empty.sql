-- **入力が空でないこと。**
--
-- 多くの検査は「差が無いこと」を見るので、**両側が空だと全部通る。**
-- 原典が1 direction 落ちた、取得が失敗した、といったときに
-- 検査は全部緑のまま配布物だけ空になる。それを塞ぐ。
--
-- ⚠️ **以前ここは原理的に落ちない検査だった。**
-- 宣言（`budget_units()`）から作った `wanted` と `actual` を full outer join していたが、
-- 両方とも同じ Jinja のループから生成され、`count(*)` は必ず1行返すので、
-- join が差を出すことがなかった。**宣言に無いものは宣言と突き合わせても見つからない。**
-- 宣言と原典のずれは declarations_cover_raw.sql が原典の側を母集団にして見る。
-- ここが見るのは「宣言した単位に中身があるか」だけでよい。
select jurisdiction, direction, rows
from (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, count(*) as rows
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
where rows = 0
