-- 公開PDF左頁の節別内訳を1対1で型付けする。説明欄の葉とは別入力。
select cast(jurisdiction as varchar) as jurisdiction_code, cast(year as integer) as fiscal_year,
       direction, document_kind, edition as origin_sha256, "table" as source_table_id,
       source_row, "会計名称" as fund_label,
       "款" as kan_code, "款名称" as kan_label,
       "項" as kou_code, "項名称" as kou_label,
       "目" as moku_code, "目名称" as moku_label,
       "節" as setsu_code, "節名称" as setsu_label,
       cast("本年度予算額" as bigint) as source_amount, source_amount_unit,
       source_page, source_bbox, reconciled,
       jurisdiction_code || ':' || fiscal_year || ':expenditure:' || document_kind || ':' || edition || ':' || "table" as dataset_id,
       dataset_id || ':' || source_row as observation_id
from {{ source('raw_131016_moku_setsu', 'data') }}
