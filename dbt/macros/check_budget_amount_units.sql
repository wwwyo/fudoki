{#
  金額の宣言（`budget_amounts`）が単位について嘘をついていないかを見る。
  経緯（なぜ宣言を2つ持たないか）は AGENTS.md の「宣言どうしの矛盾は…」の節にある。

  ⚠️ **母集団は宣言から取る**（`budget_amount_units()`）。以前は `budget_staging` の中から
  そのモデルが受け取った `amounts` に対して呼んでいたが、それだと検査が発火する条件が
  「単位が宣言されていること」ではなく「その団体の staging が `budget_staging()` を
  呼んでいること」になる。staging を手書きした団体だけ黙って無検査になり、
  **団体ごとに検査が掛かったり掛からなかったりする**（`declarations_cover_raw` が
  防ごうとしている失敗と同じ形）。

  見るのは2つ。

    1. 単位と倍率の対応（`budget_amount_unit_multipliers`）。
       `{unit: 千円, multiplier: 1}` は**どの検査も通る**（`value` も検算も同じ宣言から出るので、
       全体が 1000 分の 1 になったまま整合してしまう）。ここだけがそれを止める。
    2. 原典の列名が名乗っている単位との一致。`予算現額(千円)` のように括弧の中で
       単位を名乗る列が対象で、名乗らない列（三鷹市の `08予算額`）は突き合わせる相手がいない。

  ⚠️ **2 は語彙に登録済みの単位だけを探さない。** `budget_amount_unit_multipliers` の
  キーだけを探すと、原典が `(百万円)` で宣言が `円` のときに**未登録ゆえ照合されず通る**
  （登録漏れが検査の穴になる、という逆立ちした構造になる）。括弧の中の「〜円」を
  形で拾い、宣言と違えば止める。未登録の単位はそのまま 1 に落ちる。
#}
{% macro check_budget_amount_units() %}
{%- set table = var('budget_amount_unit_multipliers') -%}
{%- for code, direction, a in budget_amount_units() -%}

  {%- if a['unit'] not in table -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ '/' ~ a['phase'] ~ ': 単位「' ~ a['unit'] ~ '」が '
        ~ 'budget_amount_unit_multipliers に無い。倍率と対で宣言すること'
        ~ '（宣言せずに使うと、倍率が正しいかを誰も見ていない状態になる）') }}
  {%- elif a['multiplier'] != table[a['unit']] -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ '/' ~ a['phase'] ~ ': 単位「' ~ a['unit'] ~ '」の倍率は '
        ~ table[a['unit']] ~ ' のはずだが ' ~ a['multiplier'] ~ ' と宣言されている') }}
  {%- endif -%}

  {#- 原典の列名が括弧の中で名乗っている単位。`（単位：千円）` のような書き方も拾う。 -#}
  {%- set labelled = [] -%}
  {%- for inside in modules.re.findall('[（(\\[［]([^）)\\]］]*)[）)\\]］]', a['source']) -%}
    {%- for unit in modules.re.findall('[千百万億兆]*円', inside) -%}
      {%- do labelled.append(unit) -%}
    {%- endfor -%}
  {%- endfor -%}
  {%- if labelled and labelled | unique | list != [a['unit']] -%}
    {{ exceptions.raise_compiler_error(
        code ~ '/' ~ direction ~ '/' ~ a['phase'] ~ ': 原典の列「' ~ a['source'] ~ '」は '
        ~ labelled | unique | join('・') ~ ' と名乗っているのに、宣言は ' ~ a['unit'] ~ ' になっている') }}
  {%- endif -%}

{%- endfor -%}
{% endmacro %}
