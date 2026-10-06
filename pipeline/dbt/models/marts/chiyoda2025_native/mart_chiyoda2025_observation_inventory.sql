-- 非加算の観測棚卸し。金額ではなく原典カバレッジの参照。
select physical_page, account, expenditure_scope, observation_count, render_sha256, render_bytes
from {{ ref('stg_native__pages') }}
