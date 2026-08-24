-- **科目カタログが配布物へ全部・正しく届いているか。**
--
-- 判断のリソース（account_names.csv）は core_budget_accounts から作る。
-- 団体を足しても pkg_<団体>__account_names を足し忘れると、**エラーにならず配布物から消える**
-- （fdp/build.py はファイルが無い判断リソースをその団体に無いものとして黙って飛ばすため）。
--
-- ⚠️ **行数の比較では足りない。** 1行の欠落と1行の重複が打ち消し合っても、
-- 別の科目の行にすり替わっても、件数は同じまま通る。キーと名称・対応の列を
-- 双方向の差集合で突き合わせる。
{% for code in var('budget_levels').keys() | list | sort %}
-- depends_on: {{ ref('pkg_' ~ code ~ '__account_names') }}
{% endfor %}

with in_core as (
    select jurisdiction_code, fiscal_year::varchar as fiscal_year, direction, fund_code,
           kan_code, coalesce(kan_name, '') as kan_name,
           kou_code, coalesce(kou_name, '') as kou_name,
           moku_code, coalesce(moku_name, '') as moku_name,
           coalesce(master_kan_code::varchar, '') as master_kan_code,
           coalesce(master_kou_code::varchar, '') as master_kou_code,
           coalesce(master_kind, '') as master_kind
    from {{ ref('core_budget_accounts') }}
),

in_package as (
    {% for code in var('budget_levels').keys() | list | sort %}
    select '{{ code }}' as jurisdiction_code, fiscal_year, direction, fund_code,
           kan_code, coalesce(kan_name, '') as kan_name,
           kou_code, coalesce(kou_name, '') as kou_name,
           moku_code, coalesce(moku_name, '') as moku_name,
           coalesce(master_kan_code, '') as master_kan_code,
           coalesce(master_kou_code, '') as master_kou_code,
           coalesce(master_kind, '') as master_kind
    from read_csv('../data/budget/datapackages/{{ code }}/account_names.csv', header = true, all_varchar = true)
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

-- ⚠️ **EXCEPT ではなく EXCEPT ALL。** EXCEPT は集合演算なので、配布物に同じ行が
-- 2行あっても重複を消して比較し、core 1行 vs 配布物2行が通ってしまう。
select 'core にあって配布物に無い' as problem, * from (select * from in_core except all select * from in_package)
union all
select '配布物にあって core に無い', * from (select * from in_package except all select * from in_core)
