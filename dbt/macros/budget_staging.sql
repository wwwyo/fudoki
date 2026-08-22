{#
  staging の本体を宣言から組み立てる。**団体を足すときにコピーを増やさない。**

  ⚠️ **これは判断を持ち込む場所ではない。** やるのは列名の付け替えと型付けだけで、
  「どの団体のどの列がどの階層か」は `dbt_project.yml` の vars が宣言している。
  マクロにしたのは、団体ごとに同じ SQL を写経すると **片方だけ直る**ためで
  （検査が5箇所で階層を手書きしていたのと同じ形）、一般化そのものが目的ではない。

  団体差はすべて宣言側に出してある。
    budget_levels                   階層の並び
    budget_source_columns           原典の列名（階層と同じ並び）
    budget_extra_key_columns        階層だけでは一意にならない団体の追加の同一性の列
    budget_code_style               セルからコードと名称を取り出す書式
    budget_label_columns            code-only の団体で名称を持つ列がどの階層に対応するか
    budget_amounts                  原典の金額列と FDP の phase の対応

  ## 識別子

  `budget_line_id` は**公開 API の一部**なので、導出を変えると配布済みの参照が壊れる。
  構成要素はコードのパスではなく**セル全文**（三鷹市の細々節は同じ節の下でコードを
  再利用するため。実測 710 箇所・1,615 行）。
  区切りは U+001F（原典に現れない制御文字）。
  phase は partition から取る（固定値にすると補正予算を足したときに食い違う）。
#}
{% macro budget_staging(code, direction) %}

{%- set levels = var('budget_levels')[code][direction] -%}
{%- set columns = var('budget_source_columns')[code][direction] -%}
{%- set extra = var('budget_extra_key_columns')[code][direction] -%}
{%- set extra_columns = var('budget_extra_key_source_columns')[code][direction] -%}
{%- set style = var('budget_code_style')[code] -%}
{%- set labels = var('budget_label_columns').get(code, {}).get(direction, {}) -%}
{%- set extra_labels = var('budget_extra_key_labels').get(code, {}).get(direction, {}) -%}
{%- set amounts = var('budget_amounts')[code][direction] -%}

{%- if levels | length != columns | length -%}
  {{ exceptions.raise_compiler_error(
      code ~ '/' ~ direction ~ ': budget_levels（' ~ levels | length ~ '）と budget_source_columns（'
      ~ columns | length ~ '）の数が違う') }}
{%- endif -%}
{%- if extra | length != extra_columns | length -%}
  {{ exceptions.raise_compiler_error(
      code ~ '/' ~ direction ~ ': budget_extra_key_columns と budget_extra_key_source_columns の数が違う') }}
{%- endif -%}

{#- 識別子の材料。階層のセル全文 + 追加の同一性の列 -#}
{%- set key_cells = [] -%}
{%- for lv in levels %}{% do key_cells.append(lv ~ '_source') %}{% endfor -%}
{%- for k in extra %}{% do key_cells.append(k ~ '_source') %}{% endfor -%}

select
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer)         as fiscal_year,
    direction,
    source_row,
{%- for lv in levels %}
    {{ trim_cell('"' ~ columns[loop.index0] ~ '"') }} as {{ lv }}_source,
{%- endfor %}
{%- for k in extra %}
    {{ trim_cell('"' ~ extra_columns[loop.index0] ~ '"') }} as {{ k }}_source,
{%- endfor %}

{%- if style == 'prefix2' %}
    -- コードと名称の分離。先頭2桁がコードで残りが名称（実測）。
    -- 桁数は団体ごとに違いうるので、宣言（budget_code_style）で切り替える。
  {%- for lv in levels %}
    regexp_extract({{ lv }}_source, '^(\d{2})')   as {{ lv }}_code,
    regexp_replace({{ lv }}_source, '^\d{2}', '') as {{ lv }}_label,
  {%- endfor %}
{%- elif style == 'code-only' %}
    -- セルはコードだけで、階層ごとの名称の列が原典に無い。
    -- ⚠️ **名称を捏造しない。** 名称を持つ列（会計名称・科目名称）だけを、
    -- 対応する階層の label に置く。対応が実際に1対1であることは
    -- tests/label_column_determines_level.sql が毎回確かめる。
    -- それ以外の階層の label は空文字で、「原典に名称が無い」ことを表す。
  {%- for lv in levels %}
    {{ lv }}_source as {{ lv }}_code,
    {% if lv in labels %}{{ trim_cell('"' ~ labels[lv] ~ '"') }}{% else %}''{% endif %} as {{ lv }}_label,
  {%- endfor %}
{%- else %}
  {{ exceptions.raise_compiler_error(code ~ ': budget_code_style「' ~ style ~ '」は未定義') }}
{%- endif %}
{%- for k in extra %}
    {{ k }}_source as {{ k }}_code,
    {% if k in extra_labels %}{{ trim_cell('"' ~ extra_labels[k] ~ '"') }}{% else %}''{% endif %} as {{ k }}_label,
{%- endfor %}

    -- **phase は partition から取る。** 固定値にすると、補正予算を足したとき
    -- partition の phase と staging の phase が食い違う（取得側は既に phase で切っている）。
    -- ⚠️ これは**文書の種類**であって、FDP の phase（行が持つ予算段階）とは別物。
    -- 決算書は1行に複数の段階の金額を持つので、そちらは package 段で展開する。
    phase as phase_id,
    -- 識別子。**公開 API の一部**なので導出を変えると permalink が全滅する。
    jurisdiction_code || ':' || fiscal_year || ':' || direction || ':' || phase || ':'
        || substr(sha256(
            jurisdiction_code || chr(31) || fiscal_year || chr(31) || direction || chr(31) || phase
            || chr(31) || {{ key_cells | join(" || chr(31) || ") }}
        ), 1, 16) as budget_line_id
{%- for a in amounts %},
    cast("{{ a['source'] }}" as bigint) as {{ a['name'] }}
{%- endfor %}
from {{ source('raw_' ~ code, direction) }}

{% endmacro %}
