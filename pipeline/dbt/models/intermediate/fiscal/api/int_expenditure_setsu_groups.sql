{#
  事業×節の集約単位と ID の生成。**budget_item_id・集約行 fiscal_line_id はここが正本。**

  - 集約するのは「同じ dataset・経路（節より上）・追加区分・節」の末端行だけ。
    別年度・別資料・別事業・別追加区分・別の節は混ぜない。
  - 分類（COFOG・連結判断）が内訳ごとに違うときは一つの分類や消去を
    全内訳へ押し付けず、`origin_line` のまま残す。
  - 集約対象の ID は団体・年度・会計・経路・節から作る。
    原典版（dataset）をまたいで同じ対象とみなすかは、資料間の確認済み対応で決める
    ことなので、`budget_item_id` には dataset を入れない。
    集約行の `fiscal_line_id` は dataset・経路・追加区分・節から作る。
  - `origin_line` の行は従来どおり原典行 1 行を対象とし、
    確認した節は `expenditure_setsu_id` に残す。
#}
with l as (
  select *,
    count(distinct coalesce(cofog_code,'') || '|' || cofog_status || '|' || cofog_basis
      || '|' || consolidation || '|' || counterpart_fund)
      over (partition by dataset_id, group_path_key, expenditure_setsu_id) as classifications,
    min(source_row) over (partition by dataset_id, group_path_key, expenditure_setsu_id) as first_source_row
  from {{ ref('int_expenditure_setsu_lines') }}
)
select *,
  case when expenditure_setsu_id is not null and classifications = 1
       then 'expenditure_setsu' else 'origin_line' end as line_granularity,
  case when expenditure_setsu_id is not null and classifications = 1
       then 'b-' || sha256('expenditure_setsu' || chr(31) || jurisdiction_code || chr(31)
             || fiscal_year || chr(31) || fund_code || chr(31) || group_path_key
             || chr(31) || expenditure_setsu_id)
       else 'b-' || sha256(fiscal_line_id) end as budget_item_id,
  dataset_id || ':' || substr(sha256(
      'expenditure_setsu' || chr(31) || dataset_id || chr(31) || group_path_key
      || chr(31) || coalesce(expenditure_setsu_id, fiscal_line_id)), 1, 16) as group_line_id
from l
