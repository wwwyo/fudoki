{#
  **年度・文書種類で割れる宣言を解決する。**

  `document_kinds` は任意で、省略時は全文書へ効く。同年度の予算・決算は
  原典の異なる金額列・単位・段階を持つため、CASEと検査の述語を文書種類でも絞る。

  `fiscal_amounts` は長く (団体, direction) の粒度で、その団体のその方向では
  列名も単位も年度によらず同じ、という前提だった。多摩市の令和7年度で前提が崩れた —
  同じ資料の同じ団体で、金額の列名が `予算額` から `合計 / 予算額` へ、
  単位が千円から円へ変わった。

  ⚠️ **粒度を (団体, direction, 年度) へ丸ごと下げていない。** 割れているのは
  62団体のうち1団体の1年度で、下げると三鷹市も狛江市も同じ宣言を年度の数だけ写経することになる
  （写経は片方だけ直る、というのがマクロを切った当の理由）。
  代わりに各宣言へ任意の `years` を持たせ、**書かなければ全年度**という既定を残した。

  ## 解決の規則

  同じ `name` の宣言が複数あるとき、ある年度に効くのは
    1. `years` にその年度を含む宣言（**互いに重なってはいけない**）
    2. 無ければ `years` を持たない宣言
  で、どちらも無ければその年度にその金額は無い。

  ⚠️ **`years` で絞った外側は、宣言が何も言っていない年度になる。**
  それを黙って許すと「取ったのに誰も見ていない」状態（原則4）が宣言の側から生まれるので、
  覆えていない年度が原典にあれば tests/amount_declarations_cover_years.sql が止める。
  母集団は宣言ではなく**原典**の側に取る。
#}

{#- (団体, direction) が持つ金額の名前。宣言の並び順を保つ -#}
{% macro fiscal_amount_names(code, direction) %}
  {%- set names = [] -%}
  {%- for a in var('fiscal_amounts')[code][direction] -%}
    {%- if a['name'] not in names %}{% do names.append(a['name']) %}{% endif -%}
  {%- endfor -%}
  {{ return(names) }}
{% endmacro %}


{#- 同じ名前を持つ宣言（年度ごとの変種）。並び順は宣言のまま -#}
{% macro fiscal_amount_variants(code, direction, name) %}
  {{ return(var('fiscal_amounts')[code][direction] | selectattr('name', 'equalto', name) | list) }}
{% endmacro %}


{#-
  その年度に効く金額の宣言の一覧。上の解決の規則そのもの。
  `year` に none を渡すと「`years` を持たない宣言だけ」＝どの宣言にも書かれていない年度になる。
-#}
{% macro fiscal_amounts_at(code, direction, year, document_kind=none) %}
  {%- set resolved = [] -%}
  {%- for name in fiscal_amount_names(code, direction) -%}
    {%- set variants = fiscal_amount_variants(code, direction, name) -%}
    {%- set scoped = [] -%}
    {%- set unscoped = [] -%}
    {%- for a in variants if a.get('document_kinds') is none or document_kind in a['document_kinds'] -%}
      {%- if a.get('years') is none %}{% do unscoped.append(a) %}
      {%- elif year is not none and year in a['years'] %}{% do scoped.append(a) %}{% endif -%}
    {%- endfor -%}
    {%- if scoped | length > 1 -%}
      {{ exceptions.raise_compiler_error(
          code ~ '/' ~ direction ~ '/' ~ name ~ ': ' ~ year ~ ' 年度に効く宣言が '
          ~ scoped | length ~ ' 件ある。years は重ねてはいけない') }}
    {%- endif -%}
    {%- if scoped %}{% do resolved.append(scoped[0]) %}
    {%- elif unscoped %}{% do resolved.append(unscoped[0]) %}{% endif -%}
  {%- endfor -%}
  {{ return(resolved) }}
{% endmacro %}


{#-
  宣言が言及している年度の全部。SQL の分岐を組む材料。
  ⚠️ **原典が持つ年度の集合ではない**（dbt は取得の宣言を読まない）。
  両者が食い違っていないことは tests/amount_declarations_cover_years.sql が見る。
-#}
{% macro fiscal_amount_declared_years(code, direction) %}
  {%- set years = [] -%}
  {%- for a in var('fiscal_amounts')[code][direction] -%}
    {%- for y in a.get('years') or [] -%}
      {%- if y not in years %}{% do years.append(y) %}{% endif -%}
    {%- endfor -%}
  {%- endfor -%}
  {{ return(years | sort) }}
{% endmacro %}


{#- その (団体, direction) に**年度で割れる宣言があるか**。無ければ SQL は分岐しない -#}
{% macro fiscal_amount_is_year_scoped(code, direction) %}
  {{ return(fiscal_amount_declared_years(code, direction) | length > 0) }}
{% endmacro %}


{#-
  1つの宣言に効く年度の述語。全年度に効く宣言では空文字（＝絞り込み無し）。

  **`years` を SQL にするのはここだけ。** 宣言を1件ずつ回る検査も、下の CASE の組み立ても
  この1本を通す。⚠️ 以前は同じ `in (...)` を CASE の側で手で組み直しており、
  `fiscal_units.sql` の冒頭が名指しで警告している失敗（同じ数行の Jinja が複数箇所へ写され、
  片方だけ直ってドリフトする）を、その警告の隣で再現していた。
  ⚠️ 検査の側でこれが無いと、年度で割れた宣言 2 件が同じ行を 2 度数える
  （package_preserves_source の多重集合が倍になる）。
-#}
{% macro fiscal_amount_year_filter(a, year_col='fiscal_year') %}
  {%- set predicates = [] -%}
  {%- if a.get('years') is not none -%}
    {%- do predicates.append(year_col ~ ' in (' ~ a['years'] | join(', ') ~ ')') -%}
  {%- endif -%}
  {%- if a.get('document_kinds') is not none -%}
    {%- do predicates.append("document_kind in ('" ~ a['document_kinds'] | join("', '") ~ "')") -%}
  {%- endif -%}
  {{ return(predicates | join(' and ')) }}
{% endmacro %}


{#-
  年度で値が変わる式を組む。**CASE を組み立てるのはここだけ。**

  `values` は `variants` と同じ並びの SQL の値（リテラルでも列参照でもよい）。
  何を値にするかは呼ぶ側が決め、**年度で選ぶという構造はここが持つ**。
  ⚠️ 以前は属性用と原典の列用で同じ骨格を2度書いており、
  「`branches` が空のときの `case  end`」のようなエッジケースを片方だけ直せる状態だった。

  年度で割れていなければ、ただの値をそのまま返す（既存の団体の SQL は 1 文字も変わらない）。
  ⚠️ **`else` を勝手に足さない。** 覆えていない年度は NULL になり、
  `value` も `source_amount` も欠けるので下流の検査が落ちる（黙って 0 にしない）。
  覆えているかは tests/amount_declarations_cover_years.sql が原典の側から見る。
-#}
{% macro fiscal_amount_case_sql(variants, values, year_col) %}
  {%- if variants | length == 1 and variants[0].get('years') is none and variants[0].get('document_kinds') is none -%}
    {{ return(values[0]) }}
  {%- endif -%}
  {%- set branches = [] -%}
  {%- set fallback = [] -%}
  {%- for a in variants -%}
    {%- set predicate = fiscal_amount_year_filter(a, year_col) -%}
    {%- if predicate -%}
      {%- do branches.append('when ' ~ predicate ~ ' then ' ~ values[loop.index0]) -%}
    {%- else -%}
      {%- do fallback.append('else ' ~ values[loop.index0]) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ return('case ' ~ branches | join(' ') ~ (' ' ~ fallback[0] if fallback else '') ~ ' end') }}
{% endmacro %}


{#-
  1つの金額について、宣言の属性を年度で選ぶ SQL 式。
    attr    宣言のキー（source / multiplier / unit / phase / phase_label）
    quote   値を文字列リテラルとして出すか
    year_col  年度を持つ列名。staging は原典の partition（`year`）、下流は `fiscal_year`
-#}
{% macro fiscal_amount_attr_sql(code, direction, name, attr, quote=false, year_col='fiscal_year') %}
  {%- set variants = fiscal_amount_variants(code, direction, name) -%}
  {%- set values = [] -%}
  {%- for a in variants -%}
    {%- do values.append("'" ~ a[attr] ~ "'" if quote else a[attr] | string) -%}
  {%- endfor -%}
  {{ return(fiscal_amount_case_sql(variants, values, year_col)) }}
{% endmacro %}


{#-
  原典の金額の列を年度で選ぶ式。staging は bigint にし、原典突合の検査は
  `cast_bigint=false` で原文のまま取る（**text → bigint の変換が無損失か**も
  多重集合の一致で見たいので、原典側を先に数値へ潰さない）。
  ⚠️ 年度で列名が割れる団体は、raw の Parquet の列構成そのものが年度で違う
  （多摩市の令和7年度の歳出には `年度` の列が無い）。だから
  `_sources.yml` 側で `union_by_name=true` を宣言しておく必要がある。
-#}
{% macro fiscal_amount_source_sql(code, direction, name, year_col='fiscal_year', cast_bigint=true) %}
  {%- set variants = fiscal_amount_variants(code, direction, name) -%}
  {%- set values = [] -%}
  {%- for a in variants -%}
    {%- do values.append('cast("' ~ a['source'] ~ '" as bigint)' if cast_bigint else '"' ~ a['source'] ~ '"') -%}
  {%- endfor -%}
  {{ return(fiscal_amount_case_sql(variants, values, year_col)) }}
{% endmacro %}


{#- 円へ直した値。倍率が年度で割れていれば CASE になる -#}
{% macro fiscal_amount_value_sql(code, direction, name, year_col='fiscal_year') %}
  {{ return(name ~ ' * (' ~ fiscal_amount_attr_sql(code, direction, name, 'multiplier', false, year_col) ~ ')') }}
{% endmacro %}


{#-
  単位を配布物の**行の列**（`source_amount_unit`）で持つか、descriptor の定数にできるか。

  ⚠️ **package モデルと descriptor が別々に決めない。** 列を出すのは dbt のモデル、
  定数を宣言するのは `fdp/build.py` で、実装言語が違うぶん判断が2箇所に割れやすい。
  片方だけ直すと、CSV に列があるのに descriptor が定数だと言う（あるいはその逆の）
  状態になる。そこで**規則をここに1つ置き、モデルはこれを見る**。
  Python 側は同名の `unit_is_column()` が同じ規則を持ち、食い違いは
  `verify_against_csv` が配布物そのものを見て止める。

  規則は「宣言が1つか」であって「単位が1種類か」ではない。狛江市の歳出は3段階とも円だが、
  段階ごとの行へ展開する以上その行が何の単位かは行が言うべきで、定数にはできない。
-#}
{% macro fiscal_amount_unit_is_column(code, direction) %}
  {{ return(var('fiscal_amounts')[code][direction] | length > 1) }}
{% endmacro %}


{#-
  その (団体, direction) に現れる予算段階。**行を段階ごとに展開するかの判断はこれで決める。**
  ⚠️ **宣言の件数で決めない。** 多摩市は宣言が 2 件（年度で割れている）あるが
  段階は approved の 1 つだけで、行の展開は要らない。
#}
{% macro fiscal_phase_ids(code, direction) %}
  {%- set phases = [] -%}
  {%- for a in var('fiscal_amounts')[code][direction] -%}
    {%- if a['phase'] not in phases %}{% do phases.append(a['phase']) %}{% endif -%}
  {%- endfor -%}
  {{ return(phases) }}
{% endmacro %}


{#-
  年度で割れた宣言の解決が成立しているか。**モデルを 1 つ組む前にコンパイルで止める。**

  見るのは3つ。
    1. 同じ名前の宣言のうち `years` を持たないものは高々1つ（既定は1つしか置けない）
    2. `years` が重なっていない（重なると年度ごとの解決が一意に決まらない）
    3. **どの年度でも primary がちょうど1つ**。宣言の件数ではなく年度ごとに見る —
       件数で見ると、年度で割れた 2 件がどちらも primary の多摩市が「primary が2件」で落ちる
  ⚠️ 「宣言が覆えていない年度が原典にある」はここでは見られない（dbt は取得の宣言を読まない）。
  それは tests/amount_declarations_cover_years.sql が原典の側から見る。
#}
{% macro check_fiscal_amount_scopes() %}
{%- for code, direction in fiscal_units() -%}
  {%- set kinds = [none] -%}
  {%- for a in var('fiscal_amounts')[code][direction] -%}
    {%- if a.get('document_kinds') is not none and not a['document_kinds'] -%}
      {{ exceptions.raise_compiler_error(code ~ ': document_kinds must not be empty') }}
    {%- endif -%}
    {%- for kind in a.get('document_kinds', []) -%}
      {%- if kind not in ['budget', 'supplementary', 'settlement'] -%}
        {{ exceptions.raise_compiler_error(code ~ ': invalid document_kind ' ~ kind) }}
      {%- endif -%}
      {%- if kind not in kinds %}{% do kinds.append(kind) %}{% endif -%}
    {%- endfor -%}
  {%- endfor -%}
  {%- for kind in kinds -%}
    {%- set active = [] -%}
    {%- for a in var('fiscal_amounts')[code][direction] if a.get('document_kinds') is none or kind in a['document_kinds'] -%}
      {%- do active.append(a) -%}
    {%- endfor -%}
    {%- if active -%}
      {%- for name in fiscal_amount_names(code, direction) -%}
        {%- set variants = active | selectattr('name', 'equalto', name) | list -%}
        {%- if variants | rejectattr('years', 'defined') | list | length > 1 -%}
          {{ exceptions.raise_compiler_error(code ~ '/' ~ direction ~ '/' ~ kind ~ '/' ~ name ~ ': multiple defaults') }}
        {%- endif -%}
        {%- set seen = [] -%}
        {%- for a in variants -%}
          {%- if a.get('years') is not none and not a['years'] -%}
            {{ exceptions.raise_compiler_error(code ~ ': years must not be empty') }}
          {%- endif -%}
          {%- for year in a.get('years', []) -%}
            {%- if year in seen -%}
              {{ exceptions.raise_compiler_error(code ~ '/' ~ direction ~ '/' ~ kind ~ '/' ~ name ~ ': overlapping year ' ~ year) }}
            {%- endif -%}
            {%- do seen.append(year) -%}
          {%- endfor -%}
        {%- endfor -%}
      {%- endfor -%}
      {%- set years = [] -%}
      {%- for a in active -%}
        {%- for year in a.get('years', []) -%}
          {%- if year not in years %}{% do years.append(year) %}{% endif -%}
        {%- endfor -%}
      {%- endfor -%}
      {%- if active | rejectattr('years', 'defined') | list %}{% do years.append(none) %}{% endif -%}
      {%- for year in years -%}
        {%- set primary = fiscal_amounts_at(code, direction, year, kind) | selectattr('primary') | list -%}
        {%- if primary | length != 1 -%}
          {{ exceptions.raise_compiler_error(code ~ '/' ~ direction ~ '/' ~ kind ~ '/' ~ year ~ ': primary must resolve exactly once') }}
        {%- endif -%}
      {%- endfor -%}
    {%- endif -%}
  {%- endfor -%}
{%- endfor -%}
{% endmacro %}
