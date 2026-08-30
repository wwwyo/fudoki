{#
  **年度で割れる宣言を解決する。**

  `budget_amounts` は長く (団体, direction) の粒度で、その団体のその方向では
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

{#- その宣言が効く年度。`years` が無ければ none（＝全年度） -#}
{% macro budget_amount_years(a) %}{{ return(a.get('years')) }}{% endmacro %}


{#- (団体, direction) が持つ金額の名前。宣言の並び順を保つ -#}
{% macro budget_amount_names(code, direction) %}
  {%- set names = [] -%}
  {%- for a in var('budget_amounts')[code][direction] -%}
    {%- if a['name'] not in names %}{% do names.append(a['name']) %}{% endif -%}
  {%- endfor -%}
  {{ return(names) }}
{% endmacro %}


{#- 同じ名前を持つ宣言（年度ごとの変種）。並び順は宣言のまま -#}
{% macro budget_amount_variants(code, direction, name) %}
  {{ return(var('budget_amounts')[code][direction] | selectattr('name', 'equalto', name) | list) }}
{% endmacro %}


{#-
  その年度に効く金額の宣言の一覧。上の解決の規則そのもの。
  `year` に none を渡すと「`years` を持たない宣言だけ」＝どの宣言にも書かれていない年度になる。
-#}
{% macro budget_amounts_at(code, direction, year) %}
  {%- set resolved = [] -%}
  {%- for name in budget_amount_names(code, direction) -%}
    {%- set variants = budget_amount_variants(code, direction, name) -%}
    {%- set scoped = [] -%}
    {%- set unscoped = [] -%}
    {%- for a in variants -%}
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
{% macro budget_amount_declared_years(code, direction) %}
  {%- set years = [] -%}
  {%- for a in var('budget_amounts')[code][direction] -%}
    {%- for y in a.get('years') or [] -%}
      {%- if y not in years %}{% do years.append(y) %}{% endif -%}
    {%- endfor -%}
  {%- endfor -%}
  {{ return(years | sort) }}
{% endmacro %}


{#- その (団体, direction) に**年度で割れる宣言があるか**。無ければ SQL は分岐しない -#}
{% macro budget_amount_is_year_scoped(code, direction) %}
  {{ return(budget_amount_declared_years(code, direction) | length > 0) }}
{% endmacro %}


{#-
  1つの金額について、宣言の属性を年度で選ぶ SQL 式。

  年度で割れていなければただの定数になる（既存の団体の SQL は 1 文字も変わらない）。
  割れているときだけ CASE になる。
    attr    宣言のキー（source / multiplier / unit / phase / phase_label）
    quote   値を文字列リテラルとして出すか
    year_col  年度を持つ列名。staging は原典の partition（`year`）、下流は `fiscal_year`
  ⚠️ **`else` を付けない。** 覆えていない年度は NULL になり、
  `value` も `source_amount` も欠けるので下流の検査が落ちる（黙って 0 にしない）。
-#}
{% macro budget_amount_attr_sql(code, direction, name, attr, quote=false, year_col='fiscal_year') %}
  {%- set variants = budget_amount_variants(code, direction, name) -%}
  {%- set lit -%}
    {%- if quote %}'{{ variants[0][attr] }}'{% else %}{{ variants[0][attr] }}{% endif -%}
  {%- endset -%}
  {%- if variants | length == 1 and variants[0].get('years') is none -%}
    {{ return(lit) }}
  {%- endif -%}
  {%- set branches = [] -%}
  {%- set fallback = [] -%}
  {%- for a in variants -%}
    {%- set value -%}
      {%- if quote %}'{{ a[attr] }}'{% else %}{{ a[attr] }}{% endif -%}
    {%- endset -%}
    {%- if a.get('years') is none -%}
      {%- do fallback.append('else ' ~ value) -%}
    {%- else -%}
      {%- do branches.append('when ' ~ year_col ~ ' in ('
            ~ a['years'] | join(', ') ~ ') then ' ~ value) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ return('case ' ~ branches | join(' ') ~ (' ' ~ fallback[0] if fallback else '') ~ ' end') }}
{% endmacro %}


{#-
  原典の金額の列を年度で選ぶ式。staging は bigint にし、原典突合の検査は
  `cast_bigint=false` で原文のまま取る（**text → bigint の変換が無損失か**も
  多重集合の一致で見たいので、原典側を先に数値へ潰さない）。
  ⚠️ 年度で列名が割れる団体は、raw の Parquet の列構成そのものが年度で違う
  （多摩市の令和7年度の歳出には `年度` の列が無い）。だから
  `_sources.yml` 側で `union_by_name=true` を宣言しておく必要がある。
-#}
{% macro budget_amount_source_sql(code, direction, name, year_col='fiscal_year', cast_bigint=true) %}
  {%- set variants = budget_amount_variants(code, direction, name) -%}
  {%- set open = 'cast("' if cast_bigint else '"' -%}
  {%- set close = '" as bigint)' if cast_bigint else '"' -%}
  {%- if variants | length == 1 and variants[0].get('years') is none -%}
    {{ return(open ~ variants[0]['source'] ~ close) }}
  {%- endif -%}
  {%- set branches = [] -%}
  {%- set fallback = [] -%}
  {%- for a in variants -%}
    {%- set value = open ~ a['source'] ~ close -%}
    {%- if a.get('years') is none -%}
      {%- do fallback.append('else ' ~ value) -%}
    {%- else -%}
      {%- do branches.append('when ' ~ year_col ~ ' in ('
            ~ a['years'] | join(', ') ~ ') then ' ~ value) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ return('case ' ~ branches | join(' ') ~ (' ' ~ fallback[0] if fallback else '') ~ ' end') }}
{% endmacro %}


{#- 円へ直した値。倍率が年度で割れていれば CASE になる -#}
{% macro budget_amount_value_sql(code, direction, name, year_col='fiscal_year') %}
  {{ return(name ~ ' * (' ~ budget_amount_attr_sql(code, direction, name, 'multiplier', false, year_col) ~ ')') }}
{% endmacro %}


{#-
  1つの宣言に効く年度の述語。全年度に効く宣言では空文字（＝絞り込み無し）。
  **宣言を1件ずつ回る検査が使う。**
  ⚠️ これが無いと、年度で割れた宣言 2 件が同じ行を 2 度数える
  （package_preserves_source の多重集合が倍になる）。
-#}
{% macro budget_amount_year_filter(a, year_col='fiscal_year') %}
  {%- if a.get('years') is none -%}
    {{ return('') }}
  {%- endif -%}
  {{ return(year_col ~ ' in (' ~ a['years'] | join(', ') ~ ')') }}
{% endmacro %}


{#-
  その (団体, direction) に現れる予算段階。**行を段階ごとに展開するかの判断はこれで決める。**
  ⚠️ **宣言の件数で決めない。** 多摩市は宣言が 2 件（年度で割れている）あるが
  段階は approved の 1 つだけで、行の展開は要らない。
#}
{% macro budget_phase_ids(code, direction) %}
  {%- set phases = [] -%}
  {%- for a in var('budget_amounts')[code][direction] -%}
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
{% macro check_budget_amount_scopes() %}
{%- for code, direction in budget_units() -%}
  {%- for name in budget_amount_names(code, direction) -%}
    {%- set variants = budget_amount_variants(code, direction, name) -%}
    {%- set unscoped = variants | rejectattr('years', 'defined') | list -%}
    {%- if unscoped | length > 1 -%}
      {{ exceptions.raise_compiler_error(
          code ~ '/' ~ direction ~ '/' ~ name ~ ': years を持たない宣言が '
          ~ unscoped | length ~ ' 件ある。全年度に効く宣言は1つだけ') }}
    {%- endif -%}
    {%- set seen = [] -%}
    {%- for a in variants -%}
      {%- for y in a.get('years') or [] -%}
        {%- if y in seen -%}
          {{ exceptions.raise_compiler_error(
              code ~ '/' ~ direction ~ '/' ~ name ~ ': ' ~ y ~ ' 年度が複数の宣言に現れる') }}
        {%- endif -%}
        {%- do seen.append(y) -%}
      {%- endfor -%}
    {%- endfor -%}
  {%- endfor -%}

  {#- 年度ごとの解決。宣言が言及する年度と、どこにも書かれていない年度（none）を見る -#}
  {%- set buckets = budget_amount_declared_years(code, direction) -%}
  {%- set has_unscoped = var('budget_amounts')[code][direction]
                         | rejectattr('years', 'defined') | list | length > 0 -%}
  {%- for year in buckets + ([none] if has_unscoped else []) -%}
    {%- set resolved = budget_amounts_at(code, direction, year) -%}
    {%- set primary = resolved | selectattr('primary') | list -%}
    {%- if primary | length != 1 -%}
      {{ exceptions.raise_compiler_error(
          code ~ '/' ~ direction ~ '/' ~ (year or '既定') ~ ': primary が ' ~ primary | length
          ~ ' 件。集計に使う段階は年度ごとに1つでなければならない') }}
    {%- endif -%}
  {%- endfor -%}
{%- endfor -%}
{% endmacro %}
