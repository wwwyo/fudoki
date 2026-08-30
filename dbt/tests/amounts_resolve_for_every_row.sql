-- **宣言した金額が、全部の行で実際に解けていること。**
--
-- ⚠️ **`union_by_name` を使う団体では、列名の書き間違いが例外にならない。**
-- 無い列は NULL として読まれるので、多摩市の令和7年度の宣言に旧年度の列名（`予算額`）を
-- 誤って書いても、その列は他の年度のファイルに実在するぶん union 後のスキーマには現れ、
-- **その年度だけ静かに NULL になる**。
--
-- ⚠️ **原典突合では捕まらない。** `canonical_preserves_source` は原典の側にも同じ解決マクロを
-- 当てるので、両側とも NULL になって一致してしまう。宣言どうしを突き合わせる検査が
-- 何も言わないのと同じ形（AGENTS.md「宣言どうしの矛盾は…」）で、
-- **突き合わせる相手を「値が存在すること」に取り直す**ほかない。
--
-- ⚠️ **母集団は宣言。** `_models.yml` の `not_null` は団体ごとに手で登録する形なので、
-- 登録し忘れた団体（実際に多摩市が登録されていなかった）は一度も検査されない。
-- ここは `budget_amount_units()` から回るので、宣言した金額は必ず対象になる。
{% for code, direction, a in budget_amount_units() %}
{% set years = budget_amount_year_filter(a) %}
select
    '{{ code }}'      as jurisdiction,
    '{{ direction }}' as direction,
    '{{ a["name"] }}' as amount,
    '{{ a["source"] }}' as source_column,
    fiscal_year,
    count(*)          as 解けなかった行
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
where {% if years %}{{ years }} and {% endif %}{{ a['name'] }} is null
group by 1, 2, 3, 4, 5
{% if not loop.last %}union all{% endif %}
{% endfor %}
