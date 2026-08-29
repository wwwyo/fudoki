{#
  金額の宣言（`budget_amounts`）が単位について嘘をついていないかを、**コンパイル時に**見る。

  ⚠️ **以前は宣言どうしを突き合わせていた。** `sources.toml` が団体ごとに
  「原典の主たる単位」を宣言し、`fdp/build.py` がそれを `budget_amounts` の
  (単位, 倍率) の集合に含まれるかで見ていた。集合は direction をまたいで合算されていたので、
  歳出が円で歳入の primary が千円の団体では、歳出のおかげで円が集合に入り、
  **歳入の primary が食い違ったまま通った**（狛江市 132195 で実際に起きていた）。

  ⚠️ **突き合わせる相手を宣言から原典へ移した。** 宣言を2つ持てば、どちらが正かを決める
  規則が要るうえ、両方まとめて間違っているときは何も言わない。原典の列名は
  `予算現額(千円)` のように単位を自分で名乗っているので、そちらと突き合わせる。

  見るのは2つ。

    1. 単位と倍率の対応（`budget_amount_unit_multipliers`）。
       `{unit: 千円, multiplier: 1}` は**どの検査も通る**（value も検算も同じ宣言から出るので、
       全体が 1000 分の 1 になったまま整合してしまう）。ここだけがそれを止める。
    2. 原典の列名が名乗っている単位との一致。名乗っていない列（三鷹市の `08予算額`）は
       突き合わせる相手がいないので、1 だけが掛かる。
#}
{% macro check_budget_amount_units(code, direction, amounts) %}
{%- set table = var('budget_amount_unit_multipliers') -%}
{%- for a in amounts -%}

  {%- if a['unit'] not in table -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ ': 単位「' ~ a['unit'] ~ '」が budget_amount_unit_multipliers に無い。'
        ~ '倍率と対で宣言すること（宣言せずに使うと、倍率が正しいかを誰も見ていない状態になる）') }}
  {%- elif a['multiplier'] != table[a['unit']] -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ '/' ~ a['phase'] ~ ': 単位「' ~ a['unit'] ~ '」の倍率は '
        ~ table[a['unit']] ~ ' のはずだが ' ~ a['multiplier'] ~ ' と宣言されている') }}
  {%- endif -%}

  {#- 原典の列名が括弧で名乗っている単位。名乗っていなければ none。 -#}
  {%- set ns = namespace(labelled=none) -%}
  {%- for unit in table -%}
    {%- if ('(' ~ unit ~ ')') in a['source'] or ('（' ~ unit ~ '）') in a['source'] -%}
      {%- set ns.labelled = unit -%}
    {%- endif -%}
  {%- endfor -%}
  {%- if ns.labelled is not none and ns.labelled != a['unit'] -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ '/' ~ a['phase'] ~ ': 原典の列「' ~ a['source'] ~ '」は '
        ~ ns.labelled ~ ' と名乗っているのに、宣言は ' ~ a['unit'] ~ ' になっている') }}
  {%- endif -%}

{%- endfor -%}
{% endmacro %}
