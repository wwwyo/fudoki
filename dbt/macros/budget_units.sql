{#
  収録の単位 `(団体コード, direction)` の一覧。**検査が母集団を各自で導出しない。**

  ⚠️ **同じ4行の Jinja が10箇所へコピーされ、既にドリフトしていた。**
  `| sort` の有無、`.keys()` と `.items()` の違い、ローカル変数名が `codes` / `blocks` /
  `expected` とばらばら。`budget_levels` は「階層の並び」と「収録済みの単位の登録簿」を
  兼ねているので、後者の意味が変わったとき（歳出しか無い団体、単位ごとの除外）に
  10ファイルを直すことになり、直し忘れた検査は古い母集団を検査したまま通る。
  それは budget_core_covers_all_staging が防ごうとしている失敗そのものである。

  ⚠️ **平坦なリストで返す。** 入れ子のループだと `loop.last` が内側にしか効かず、
  各ファイルが末尾に `select null, ... where false` の番人を置く羽目になる
  （列数を数え間違えると、そこだけ静かに壊れる）。平坦なら `{% if not loop.last %}` が効く。
#}
{% macro budget_units() %}
  {%- set units = [] -%}
  {%- for code in var('budget_levels').keys() | list | sort -%}
    {%- for direction in var('budget_levels')[code].keys() | list | sort -%}
      {%- do units.append((code, direction)) -%}
    {%- endfor -%}
  {%- endfor -%}
  {{ return(units) }}
{% endmacro %}


{#
  収録の単位を金額の段階まで割ったもの `(団体コード, direction, 金額の宣言)`。
  決算書は1行が複数段階の金額を持つので、段階ごとに見る検査はこちらを使う。
#}
{% macro budget_amount_units() %}
  {%- set units = [] -%}
  {%- for code, direction in budget_units() -%}
    {%- for amount in var('budget_amounts')[code][direction] -%}
      {%- do units.append((code, direction, amount)) -%}
    {%- endfor -%}
  {%- endfor -%}
  {{ return(units) }}
{% endmacro %}
