{{ config(materialized = 'external', location = '../data/budget/packages/derived/cofog.csv', format = 'csv') }}
-- 派生。**団体をまたいで1リソース。**
--
-- 置き場を `derived/` にしているのは、**正本か派生かがパスで区別される必要がある**から。
-- 中身が COFOG であることは datapackage.json の title と description が言うので、
-- パスに書かない（②調達・③会議録の派生が増えたときに嘘になる）。
-- カバレッジも書かない。対象を東京の外へ広げたときに地域で切ると、
-- 年度で切ってはいけないのと同じ理由で横断できなくなる。
--
-- 団体をまたいで1つにできるのは、ここが判断の側だから。
-- 三鷹市は事項、狛江市は大事業・中事業・小事業と階層の構成が違うので、
-- 正本を1つの表に揃えるのは「この2つは同じ概念だ」という判断になる。
-- 揃える判断も COFOG の割当も同じ側にあるので、横断はここでだけ成立する。
--
-- **識別子と判断だけを持つ。** 正本の列を複製しない。
-- 複製すると容量が倍になるうえ、「fudoki が付け加えたのはどこか」を見るのに
-- 2ファイルの diff が要る状態になる。正本とは budget_line_id で join する。
--
-- 根拠（basis）もここには置かない。**規則ごとに1つ**なので行に複製すると
-- ファイルの大半が同じ文字列の繰り返しになる（実測 1,150 KB のうち大半）。
-- cofog_rules.csv に規則表として出し、cofog_rule_id で join する。
select
    c.jurisdiction_code,
    c.fiscal_year,
    c.direction,
    s.budget_line_id,
    c.cofog_status,
    c.cofog_division,
    c.cofog_consolidation,
    c.cofog_decided_at_level,
    c.cofog_rule_id,
    c.cofog_counterpart_fund
from {{ ref('core_budget_cofog') }} as c
inner join {{ ref('stg_132047__expenditure') }} as s using (budget_line_id)

union all

select
    c.jurisdiction_code,
    c.fiscal_year,
    c.direction,
    s.budget_line_id,
    c.cofog_status,
    c.cofog_division,
    c.cofog_consolidation,
    c.cofog_decided_at_level,
    c.cofog_rule_id,
    c.cofog_counterpart_fund
from {{ ref('core_revenue_consolidation') }} as c
inner join {{ ref('stg_132047__revenue') }} as s using (budget_line_id)

-- **並びを固定する。** 指定しないと実行ごとに行順が変わり、
-- 中身が同じでも git に毎回 2,048 行の差分が出る。
-- リポジトリで配る以上、決定的でない成果物は「変わっていない」を主張できない。
order by jurisdiction_code, fiscal_year, direction, budget_line_id
