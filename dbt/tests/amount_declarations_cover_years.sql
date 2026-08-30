-- **原典が持つ年度が、金額の宣言に全部覆われているか。**
--
-- `budget_amounts` の宣言は `years` で年度を絞れる（多摩市は令和7年度で列名と単位が変わった）。
-- ⚠️ **絞れるということは、絞り忘れた年度を誰も見ない状態が作れるということでもある。**
-- 覆われていない年度の行は `source_amount` が NULL になるだけで、
-- 「その年度の金額が無い」という嘘が静かに配布物へ入る。
--
-- ⚠️ **だから母集団を宣言ではなく原典に取る**（`declarations_cover_raw` と同じ理由）。
-- 宣言の側から回すと、宣言に書いていない年度は最初から見えない。
--
-- ⚠️ 年度で割れていない団体（全ての宣言が `years` を持たない）はここでは何も見ない —
-- 見る必要が無いのではなく、**全年度に効く宣言があるので覆われないことが起きない**。
{% set scoped = [] %}
{% for code, direction in budget_units() %}
  {% if budget_amount_is_year_scoped(code, direction) %}
    {% for name in budget_amount_names(code, direction) %}
      {#- 全年度に効く変種があれば、その名前は年度によらず必ず解決する -#}
      {% set variants = budget_amount_variants(code, direction, name) %}
      {% if variants | rejectattr('years', 'defined') | list | length == 0 %}
        {#-
          ⚠️ **年度の集合は「その名前の変種」から作る。direction 全体の和集合ではない。**
          和集合を使うと、金額 A が [2021]・金額 B が [2022] のとき両方が [2021, 2022] で
          検査され、**A の 2022 と B の 2021 の欠落を互いに埋め合って**通ってしまう。
        -#}
        {% set years = [] %}
        {% for a in variants %}
          {% for y in a['years'] %}
            {% if y not in years %}{% do years.append(y) %}{% endif %}
          {% endfor %}
        {% endfor %}
        {% do scoped.append((code, direction, name, years | sort)) %}
      {% endif %}
    {% endfor %}
  {% endif %}
{% endfor %}

{% if scoped %}
{% for code, direction, name, years in scoped %}
select
    '{{ code }}'      as jurisdiction,
    '{{ direction }}' as direction,
    '{{ name }}'      as amount,
    year              as 覆われていない年度,
    count(*)          as rows
from {{ source('raw_' ~ code, direction) }}
where cast(year as integer) not in ({{ years | join(', ') }})
group by 1, 2, 3, 4
{% if not loop.last %}union all{% endif %}
{% endfor %}
{% else %}
-- 年度で割れた宣言がまだ1つも無い。列だけ揃えて何も返さない
select null as jurisdiction, null as direction, null as amount,
       null as 覆われていない年度, null as rows
where false
{% endif %}
