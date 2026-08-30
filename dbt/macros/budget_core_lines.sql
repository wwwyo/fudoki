{#
  団体をまたいだ共通の形へ揃える。**ここが2団体目で初めて必要になった判断。**

  「三鷹市の款と狛江市の款は同じ概念だ」と決めるのは fudoki の判断なので、
  staging には置けない（staging は原典と1対1で、判断を含まない）。
  AGENTS.md が「intermediate を切るのは2団体目で科目名の表記が割れたとき」と
  言っている、その時点にあたる。段を増やさず core に置いているのは、
  core の責務がまさに「団体をまたぐ整形」だから。

  ⚠️ **共通の形は最大公約数であって、正本ではない。**
  三鷹市の事項も狛江市の大事業もここには出てこない。
  階層の全部が要るときは団体ごとの staging か配布物（正本）を見る。
  ここは COFOG の規則を当てるための面で、款・項・目・節までしか要らない。

  ⚠️ **金額は `budget_amounts` で primary と宣言した段階だけを取る。**
  決算書は1行に複数段階の金額を持つので、どれで集計するかを宣言に持たせないと
  団体ごとに違う段階を足し合わせた数字が出る。
#}
{% macro budget_core_lines(direction) %}
{#-
  ⚠️ **母集団を自前で導出しない。** `budget_units()` が収録の単位の正本で、
  この PR がそこへ寄せた当のマクロがここだけ古い導出を残していた。
  導出が2箇所にあると、direction を片方しか持たない団体を足したときに片方だけ追随する。
-#}
{%- set codes = [] -%}
{%- for c, d in budget_units() if d == direction %}{% do codes.append(c) %}{% endfor -%}
{%- for code in codes %}
{#-
  ⚠️ **primary は宣言の件数ではなく年度ごとに1つ。** 多摩市は令和7年度で列名と単位が
  変わったので、同じ `source_amount` の宣言が年度で 2 件に割れている（どちらも primary）。
  件数で数えると「primary が2件」で落ちるので、年度ごとの解決を見る
  （check_budget_amount_scopes がそれをコンパイル時に確かめる）。
  ⚠️ 集計に使う金額の**名前**まで年度で割れると、この select の列が年度で変わってしまう。
  そこは割れていないことを要求する（割る必要が出たら core の形を決め直すこと）。
-#}
{%- set primary_names = [] -%}
{%- for a in var('budget_amounts')[code][direction] if a['primary'] -%}
  {%- if a['name'] not in primary_names %}{% do primary_names.append(a['name']) %}{% endif -%}
{%- endfor -%}
{%- if primary_names | length != 1 -%}
  {{ exceptions.raise_compiler_error(
      code ~ '/' ~ direction ~ ': primary の金額の名前が ' ~ primary_names
      ~ ' と複数ある。集計に使う金額は団体・direction ごとに1つでなければならない') }}
{%- endif -%}
select
    jurisdiction_code,
    fiscal_year,
    direction,
    phase_id,
    budget_line_id,
    source_row,
    fund_code,
    fund_label,
    kan_code,
    kan_label,
    kou_code,
    kou_label,
    moku_code,
    moku_label,
    setsu_code,
    setsu_label,
    source_amount,
    -- 円へ正規化した値。倍率は原典の単位の宣言から来る
    -- （三鷹市は千円、狛江市は円と千円、多摩市は年度で千円と円に割れる）
    {{ budget_amount_value_sql(code, direction, primary_names[0]) }} as amount_yen
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all
{% endif %}
{%- endfor %}
{% endmacro %}
