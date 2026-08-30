-- **年度の列を「この年度にはある」と絞ったとき、外した年度には本当に列が無いか。**
--
-- `budget_source_year_columns` の宣言は `years` で年度を絞れる
-- （多摩市の歳出は令和7年度から `年度` の列が消えた）。
-- ⚠️ **絞ると、外した年度は `source_year_matches_partition` の対象から外れる。**
-- 照合を通すために年度を外す、という逃げ道がそのまま開いてしまうので、
-- 外した年度では原典に値が1つも無いことをここで確かめる。
--
-- ⚠️ この検査が成り立つのは `union_by_name=true` で読んでいる団体だけである
-- （列が無い年度は NULL として読まれる）。列が実在して値が入っていれば、
-- それは「宣言が年度を外したのに原典は持っている」＝見ていない年度がある状態にあたる。
{% set scoped = [] %}
{% for code, direction in budget_units() %}
  {% for spec in var('budget_source_year_columns').get(code, {}).get(direction, []) %}
    {% if spec.get('years') %}
      {% do scoped.append((code, direction, spec)) %}
    {% endif %}
  {% endfor %}
{% endfor %}

{% if scoped %}
{% for code, direction, spec in scoped %}
select
    '{{ code }}'            as jurisdiction,
    '{{ direction }}'       as direction,
    '{{ spec["column"] }}'  as column_name,
    year                    as 宣言から外した年度,
    count(*)                as 値を持つ行
from {{ source('raw_' ~ code, direction) }}
where year not in ({{ spec['years'] | join(', ') }})
  and "{{ spec['column'] }}" is not null
group by 1, 2, 3, 4
{% if not loop.last %}union all{% endif %}
{% endfor %}
{% else %}
-- 年度で絞った宣言がまだ1つも無い。列だけ揃えて何も返さない
select null as jurisdiction, null as direction, null as column_name,
       null as 宣言から外した年度, null as 値を持つ行
where false
{% endif %}
