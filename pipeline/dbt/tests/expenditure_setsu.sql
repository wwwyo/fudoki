-- **歳出の節マスタと事業×節集約の不変条件。**
--
-- - 原典が節名称を印字した行は、`expenditure_setsu_map` の宣言で
--   必ず法定区分へ解決する（宣言から漏れた節は黙って原典行粒度に落ちない）。
-- - 節マスタの参照は適用期間内の年度に限る。
-- - `details_json` の内訳合計は親の `amount` と一致し、
--   原典行は内訳へちょうど一度だけ現れる（小計・合計の二重計上が無い）。
-- - 節の確かめられない行は `expenditure_setsu_id = NULL`・`origin_line` で残す。

{% set details_schema = '[{"path":"JSON","amount":"BIGINT","fiscalLineId":"VARCHAR","sourceRow":"BIGINT"}]' %}
with canonical_original as (
  select o.fiscal_line_id, o.dataset_id, o.amount
  from {{ ref('int_expenditure_setsu_lines') }} o
  where not exists (
    select 1 from {{ ref('fiscal_132195_initial_moku_reference') }} r
    where r.fiscal_line_id=o.fiscal_line_id and r.superseded_by_full_initial_detail)
  union all
  select fiscal_line_id, dataset_id, initial_yen as amount
  from {{ ref('int_132195_initial_detail') }}
  union all
  select fiscal_line_id, dataset_id, initial_yen as amount
  from {{ ref('int_132071_initial445') }}
), problems(problem, id) as (
  select 'setsu_without_map', fiscal_line_id
  from {{ ref('int_expenditure_setsu_lines') }}
  where setsu_present and expenditure_setsu_id is null

  union all
  select 'budget_item_setsu_unresolved', b.budget_item_id
  from {{ ref('fiscal_expenditure_budget_items') }} b
  left join {{ ref('fiscal_expenditure_setsu_master') }} m
    on m.expenditure_setsu_id = b.expenditure_setsu_id
  where b.expenditure_setsu_id is not null
    and (m.expenditure_setsu_id is null
         or (m.valid_from_fiscal_year is not null and b.fiscal_year < m.valid_from_fiscal_year)
         or (m.valid_to_fiscal_year is not null and b.fiscal_year > m.valid_to_fiscal_year))

  union all
  select 'aggregated_item_without_setsu', b.budget_item_id
  from {{ ref('fiscal_expenditure_budget_items') }} b
  where b.line_granularity = 'expenditure_setsu' and b.expenditure_setsu_id is null

  union all
  select 'map_without_master', m.expenditure_setsu_id
  from {{ ref('expenditure_setsu_map') }} m
  left join {{ ref('fiscal_expenditure_setsu_master') }} s
    on s.expenditure_setsu_id = m.expenditure_setsu_id
  where s.expenditure_setsu_id is null

  union all
  -- 内訳合計と親金額の不一致（小計行を二重に足した、または末端を落とした形跡）
  select 'details_amount_mismatch', l.fiscal_line_id
  from {{ ref('fiscal_initial_expenditure_budget_lines') }} l
  left join lateral (
    select sum(x.amount) as s
    from unnest(from_json(l.details_json,
      '{{ details_schema }}')) t(x)
  ) d on true
  where l.amount is distinct from d.s

  union all
  -- 原典行が複数の内訳へ重複して現れた
  select 'origin_line_reused', x.fiscalLineId
  from {{ ref('fiscal_initial_expenditure_budget_lines') }} l,
       unnest(from_json(l.details_json,
         '{{ details_schema }}')) t(x)
  group by x.fiscalLineId having count(*) > 1

  union all
  -- 集約・原典行のどちらにも取り込まれなかった予算の原典行
  select 'origin_line_dropped', o.fiscal_line_id
  from canonical_original o
  where not exists (
    select 1
    from {{ ref('fiscal_initial_expenditure_budget_lines') }} l,
         unnest(from_json(l.details_json,
           '{{ details_schema }}')) t(x)
    where x.fiscalLineId = o.fiscal_line_id)

  union all
  -- dataset ごとの総額は原典の当初予算額の合計を保つ
  select 'dataset_total_differs', coalesce(a.dataset_id, o.dataset_id)
  from (
    select dataset_id, sum(amount) as total
    from {{ ref('fiscal_initial_expenditure_budget_lines') }} group by dataset_id
  ) a
  full outer join (
    select dataset_id, sum(amount) as total
    from canonical_original group by dataset_id
  ) o using (dataset_id)
  where a.total is distinct from o.total
)
select * from problems
