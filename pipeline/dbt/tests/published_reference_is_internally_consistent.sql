-- **公表値そのものの内部整合。** 款別の和が公表の合計に戻ること。
-- 書き写しの誤りを、こちらのデータを持ち出さずに検出する。
select direction, sum(amount_thousand_yen) as 款別の和, max(m.total_thousand_yen) as 公表の合計
from {{ ref('published_reference') }} as p
cross join {{ ref('published_reference_meta') }} as m
group by direction
having sum(amount_thousand_yen) <> max(m.total_thousand_yen)
