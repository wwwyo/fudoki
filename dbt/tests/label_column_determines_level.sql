-- **名称の列が、対応づけた階層と1対1であること。**
--
-- 狛江市の原典には階層ごとの名称の列が無く、名称を持つのは会計（会計名称）と
-- 行の最下位階層（科目名称）だけである。`budget_label_columns` はその
-- 「科目名称は歳出なら節、歳入なら細節の名称」という対応を宣言している。
--
-- ⚠️ **これは実測に基づく対応であって、原典が明示しているものではない。**
-- 宣言が正しければ、同じ年度の同じ親の下で、同じコードには常に同じ名称が付く。
--
-- ⚠️ **年度をまたいで比べない。** 2020年度の地方自治法施行規則改正で歳出の節が再編され、
-- 同じ節コードが年度によって別の名称を指す（実測: 節18 は 2019年度まで備品購入費、
-- 2020年度から負担金、補助及び交付金）。年度を跨いで比べると 1,315 件落ちる。
-- 原典の作りが変わって対応が崩れたら、名称を1段ずれた階層に付けたまま配ることになるので、
-- 毎回確かめる。（三鷹市は名称がセルに同居するので、この検査の対象にならない）
{% set codes = var('budget_code_style').items() | selectattr('1', 'equalto', 'code-only') | map(attribute='0') | list | sort %}
{% for code in codes %}
{% for direction, labels in var('budget_label_columns')[code].items() %}
{% set levels = var('budget_levels')[code][direction] %}
{% for lv in labels.keys() %}
{%- set parent = [] -%}
{%- for p in levels[:levels.index(lv)] %}{% do parent.append(p ~ '_source') %}{% endfor -%}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ lv }}' as level,
       fiscal_year,
       {% if parent %}{{ parent | join(" || '/' || ") }}{% else %}''{% endif %} as parent,
       {{ lv }}_code as code, count(distinct {{ lv }}_label) as 名称の異なり数
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
group by 1, 2, 3, 4, 5, 6 having count(distinct {{ lv }}_label) > 1
union all
{% endfor %}
{% endfor %}
{% endfor %}
select null, null, null, null, null, null, null where false
