-- **原典にあるものが、全部宣言されているか。**
--
-- ⚠️ **他のほとんどの検査は宣言（`budget_levels`）を母集団にしている。**
-- だから狛江市の歳入を宣言し忘れると、raw に Parquet があっても検査は
-- 歳入を一度も見ないまま**全部緑で通る**。「差が無いこと」を見る検査は、
-- 両側が空なら成立してしまう。母集団の誤りは後段の精度改善では救えない（原則4）。
--
-- ここだけは**原典の側**を母集団にして、宣言と突き合わせる。
-- 原典は取得の単位で partition してあるので、ディレクトリ構造がそのまま集合になる。
--
-- ⚠️ 逆向き（宣言したのに raw が無い）も見る。宣言だけ足して取得を忘れた場合、
-- staging は空になり `inputs_are_not_empty` が落ちるが、原因がここのほうが読める。
with in_raw as (
    select distinct
        cast(jurisdiction as varchar) as jurisdiction,
        direction
    from read_parquet('../data/budget/raw/jurisdiction=*/year=*/phase=*/direction=*/data.parquet',
                      hive_partitioning=true)
),

declared as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    coalesce(r.jurisdiction, d.jurisdiction) as jurisdiction,
    coalesce(r.direction, d.direction)       as direction,
    r.jurisdiction is not null               as 原典にある,
    d.jurisdiction is not null               as 宣言にある
from in_raw as r
full outer join declared as d using (jurisdiction, direction)
where r.jurisdiction is null or d.jurisdiction is null
