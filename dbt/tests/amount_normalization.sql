-- **円への正規化が原典の値と倍率で説明できること。**
-- 丸めや欠損が混じっていないことを配布物の側で確かめる。
--
-- 倍率は団体・段階ごとの宣言（`budget_amounts`）から来る。
-- ⚠️ **単位は1つとは限らない。** 狛江市の歳入は予算現額が千円で収入累計が円なので、
-- 「全部千円」と決め打ちすると片方が 1000 倍ずれたまま通る。
-- ⚠️ **年度でも割れる。** 多摩市は令和3〜6年度が千円、令和7年度が円である。
{% for code, direction, a in budget_amount_units() %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ a["phase"] }}' as phase,
       budget_line_id, value, source_amount
from {{ ref('pkg_' ~ code ~ '__' ~ direction) }}
-- ⚠️ **年度で割れた宣言は、その年度の行だけを見る。** 絞らないと、多摩市の令和7年度の行を
-- 令和3〜6年度の倍率（1000）で検算して落ちる。
{% set years = budget_amount_year_filter(a) %}
where {% if years %}{{ years }} and {% endif %}
      {% if budget_phase_ids(code, direction) | length > 1 %}phase_id = '{{ a["phase"] }}' and {% endif %}
      value is distinct from source_amount * {{ a['multiplier'] }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
