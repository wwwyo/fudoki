-- **科目カタログが配布物へ全部届いているか。**
--
-- 判断のリソース（account_names.csv）は core_budget_accounts から作る。
-- 団体を足しても pkg_<団体>__account_names を足し忘れると、**エラーにならず配布物から消える**
-- （fdp/build.py はファイルが無い判断リソースをその団体に無いものとして黙って飛ばすため）。
{% for code in var('budget_levels').keys() | list | sort %}
-- depends_on: {{ ref('pkg_' ~ code ~ '__account_names') }}
{% endfor %}

with in_core as (
    select jurisdiction_code, count(*) as n
    from {{ ref('core_budget_accounts') }}
    group by 1
),

in_package as (
    {% for code in var('budget_levels').keys() | list | sort %}
    select '{{ code }}' as jurisdiction_code, count(*) as n
    from read_csv('../data/budget/datapackages/{{ code }}/account_names.csv', header = true, all_varchar = true)
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select c.jurisdiction_code, c.n as core_rows, coalesce(p.n, 0) as package_rows
from in_core as c
left join in_package as p using (jurisdiction_code)
where coalesce(p.n, 0) != c.n
