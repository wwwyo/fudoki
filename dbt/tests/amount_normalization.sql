-- **円への正規化が原典の値と倍率で説明できること。**
-- 原典は千円単位。value は円。丸めや欠損が混じっていないことを配布物の側で確かめる。
select 'expenditure' as direction, budget_line_id, value, source_amount
from {{ ref('pkg_132047__expenditure') }} where value <> source_amount * 1000
union all
select 'revenue', budget_line_id, value, source_amount
from {{ ref('pkg_132047__revenue') }} where value <> source_amount * 1000
