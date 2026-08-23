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
--
-- ⚠️ **事業名の原典もここで見る。** 詳しくは下の union all の側。
{#
  ⚠️ **事業名の原典もここで見る。** PDF から起こした抽出物は
  `raw/project-names/jurisdiction=*/year=*/` にあり、`phase=` も `direction=` も持たないので
  下の glob に掛からない。**原典の側を母集団にする唯一の検査に穴が空いていた** —
  `sources.toml` の `[project_names]` ブロックを消すと 488 件の名称が配布物から消えるのに、
  検査は全部緑のままだった（年度が両側から消えるため）。
#}
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

union all

-- 事業名の抽出物。原典にある年度が staging に全部届いているか
select jurisdiction, 'project-names' as direction, 原典にある, 宣言にある
from (
    select
        cast(jurisdiction as varchar) as jurisdiction,
        cast(year as varchar)         as year,
        true                          as 原典にある,
        false                         as 宣言にある
    from read_parquet('../data/budget/raw/project-names/jurisdiction=*/year=*/data.parquet',
                      hive_partitioning=true)
    group by 1, 2
    except
    select jurisdiction_code, cast(fiscal_year as varchar), true, false
    from {{ ref('stg_132195__project_names') }}
    group by 1, 2
)

union all

-- 歳入科目名の抽出物。原典にある年度が staging に全部届いているか
select jurisdiction, 'revenue-accounts' as direction, 原典にある, 宣言にある
from (
    select
        cast(jurisdiction as varchar) as jurisdiction,
        cast(year as varchar)         as year,
        true                          as 原典にある,
        false                         as 宣言にある
    from read_parquet('../data/budget/raw/revenue-accounts/jurisdiction=*/year=*/data.parquet',
                      hive_partitioning=true)
    group by 1, 2
    except
    select jurisdiction_code, cast(fiscal_year as varchar), true, false
    from {{ ref('stg_132195__revenue_accounts') }}
    group by 1, 2
)
