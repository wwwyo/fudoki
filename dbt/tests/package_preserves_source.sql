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
--
-- ⚠️ **1行が原典の1行とは限らない。** 決算書は1行に複数段階の金額を持ち、
-- package はそれを段階ごとの行へ展開する。だから staging 側も同じように展開して比べる。
-- 展開の仕方は `budget_amounts` の宣言が持つ。
{#-
  ⚠️ **read_csv は dbt に依存として見えない。**
  ref() を書かないと、配布物がまだ書かれていないうちにこの検査が走る
  （実際に「ファイルが無い」で落ちた）。SQL では使わないが依存として宣言する。
-#}
{% for code, direction in budget_units() %}
-- depends_on: {{ ref('pkg_' ~ code ~ '__' ~ direction) }}
{% endfor %}

with from_package as (
    {% for code, direction in budget_units() %}
    {% set lv = var('budget_levels')[code][direction] %}
    select
        '{{ code }}' as jurisdiction, fiscal_year, phase_id, '{{ direction }}' as direction,
        -- ⚠️ 空のコード（階層なしのプレースホルダ）は CSV から読み戻すと NULL になる。
        -- coalesce しないと、その行だけ丸ごと NULL の cells になって突合が壊れる。
        [{% for l in lv %}coalesce({{ l }}_code, '') || coalesce({{ l }}_label, ''), {% endfor %}
         {% for k in var('budget_extra_key_columns')[code][direction] %}coalesce({{ k }}_code, ''), {% endfor %}
         cast(source_amount as varchar)] as cells,
        count(*) as n
    -- ⚠️ **`all_varchar = true` で読む。** 狛江市のコードは先頭ゼロが無い数字なので、
    -- 型推論に任せると BIGINT になり、三鷹市（`01` 形式で VARCHAR）と型が割れて
    -- 突合そのものが組めない。原典との比較は文字列で行うのが正しい。
    from read_csv('../data/budget/packages/{{ code }}/{{ direction }}.csv',
                  header = true, all_varchar = true)
    group by 1, 2, 3, 4, 5
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

from_staging as (
    {% for code, direction, a in budget_amount_units() %}
    {% set lv = var('budget_levels')[code][direction] %}
    {% set style = var('budget_code_style')[code] %}
    select
        jurisdiction_code as jurisdiction, fiscal_year, '{{ a["phase"] }}' as phase_id, direction,
        -- code-only の団体は原文セル = コードで、名称は別列から来る。
        -- 繋いだものと突き合わせるので、package 側と同じ組み立て方をする。
        [{% for l in lv %}{% if style == 'prefix2' %}{{ l }}_source{% else %}{{ l }}_code || {{ l }}_label{% endif %}, {% endfor %}
         {% for k in var('budget_extra_key_columns')[code][direction] %}{{ k }}_source, {% endfor %}
         cast({{ a['name'] }} as varchar)] as cells,
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
