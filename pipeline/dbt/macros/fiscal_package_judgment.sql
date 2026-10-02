{#
  原典の行を保つ内部モデルと、分類判断を別の表で照合する。
  配布 CSV は歳出明細に分類列を統合するが、内部照合の対象を混ぜると
  package_preserves_source が原典と判断のどちらを保証するのか曖昧になる。
#}
{% macro fiscal_package_cofog(code) %}
{# 自動推論では 09 が数値、04.5.1 が日付になり、配布物を読み直す検査でコードが変わる。 #}
{{ config(csv_read_options={'auto_detect': true, 'types': {
    'cofog_division': 'VARCHAR', 'cofog_group': 'VARCHAR', 'cofog_class': 'VARCHAR',
    'cofog_rule_id': 'VARCHAR', 'cofog_counterpart_fund': 'VARCHAR'
}}) }}
-- COFOG の割当。**fudoki の判断**で、自治体が言っていないことを付け加えている。
-- 正本（expenditure / revenue）とは fiscal_line_id で join する。
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
    fiscal_line_id,
    cofog_status,
    -- COFOG の階層。**規則が決めた粒度までしか埋まらない**（款の名称だけで決まる
    -- 規則は division 止まりで group / class が空）。空は「まだ降りていない」であって
    -- 「該当が無い」ではない。
    cofog_division,
    cofog_group,
    cofog_class,
    cofog_consolidation,
    cofog_decided_at_level,
    cofog_rule_id,
    cofog_counterpart_fund
from (
    select * from {{ ref('core_fiscal_cofog') }}
    union all
    select * from {{ ref('core_revenue_consolidation') }}
)
where jurisdiction_code = '{{ code }}'
-- **並びを固定する。** 指定しないと実行ごとに行順が変わり、中身が同じでも毎回差分が出る。
-- リポジトリで配る以上、決定的でない成果物は「変わっていない」を主張できない。
order by fiscal_year, direction, fiscal_line_id
{% endmacro %}


{% macro fiscal_package_cofog_rules(code) %}
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
    cofog_code,
    consolidation,
    decided_at_level,
    counterpart_fund,
    basis
from {{ ref('cofog_rules') }}
where coalesce(applies_to, '') in ('', '{{ code }}')
order by priority
{% endmacro %}
