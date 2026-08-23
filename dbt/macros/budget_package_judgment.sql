{#
  COFOG の割当と、その規則表を**団体ごとの配布物**として書き出す。

  ⚠️ **判断を別パッケージへ分けない。** 以前は `derived/` に団体をまたいで1つ置いていたが、
  利用者から見ると「正本と派生を join しないと使えない」という摩擦が常にかかる一方で、
  分けたことで伝わるのは「これは判断だ」という一点だけだった。
  それは**リソースの説明と、判断を実装している code** が言えばよい。
  権利の違いは、パッケージのライセンス表示が取得元ごとに出る形（`licenses_of`）で解ける。

  ⚠️ **リソースは分けたままにする。** 正本（原典と突き合わせて検証できる）と
  判断（突き合わせる相手がいない）を1つの表へ混ぜると、`package_preserves_source` が
  何を保証しているのか言えなくなる。ファイルは分け、パッケージは1つにする。
#}
{% macro budget_package_cofog(code) %}
-- COFOG の割当。**fudoki の判断**で、自治体が言っていないことを付け加えている。
-- 正本（expenditure / revenue）とは budget_line_id で join する。
-- 根拠は cofog_rules に規則として出してあり、cofog_rule_id で引ける。
--
-- ⚠️ **識別子と判断だけを持つ。** 正本の列を複製しない。複製すると容量が倍になるうえ、
-- 「fudoki が付け加えたのはどこか」を見るのに2ファイルの diff が要る状態になる。
--
-- ⚠️ **根拠（basis）も行に複製しない。** 規則ごとに1つなので、複製するとファイルの大半が
-- 同じ文字列の繰り返しになる（実測 1,150 KB のうち大半）。規則表を cofog_rule_id で引く。
select
    fiscal_year,
    direction,
    budget_line_id,
    cofog_status,
    cofog_division,
    cofog_consolidation,
    cofog_decided_at_level,
    cofog_rule_id,
    cofog_counterpart_fund
from (
    select * from {{ ref('core_budget_cofog') }}
    union all
    select * from {{ ref('core_revenue_consolidation') }}
)
where jurisdiction_code = '{{ code }}'
-- **並びを固定する。** 指定しないと実行ごとに行順が変わり、中身が同じでも毎回差分が出る。
-- リポジトリで配る以上、決定的でない成果物は「変わっていない」を主張できない。
order by fiscal_year, direction, budget_line_id
{% endmacro %}


{% macro budget_package_cofog_rules(code) %}
-- 割り当て規則そのもの。**判断の中身を読めるようにするため。**
-- 分類結果だけを配ると、利用者は結果を検算できても判断を検討できない。
--
-- ⚠️ **その団体に効く規則だけを出す。** 空の applies_to は法定語彙（款・節）に当たる
-- 共通規則で、どの団体にも効く。他団体だけに効く規則を混ぜると、
-- 「この配布物のどれが自分に関係あるのか」が読めなくなる。
select
    priority,
    rule_id,
    applies_to,
    match_fund,
    match_kan,
    match_kou,
    match_kan_code,
    match_moku,
    moku_mode,
    match_setsu,
    status,
    division,
    consolidation,
    decided_at_level,
    counterpart_fund,
    basis
from {{ ref('cofog_rules') }}
where coalesce(applies_to, '') in ('', '{{ code }}')
order by priority
{% endmacro %}
