-- **対応表の参照先がマスタに実在するか。**
--
-- account_map の master_kan_code / master_kou_code はマスタへの外部キーだが、
-- seed どうしなので DB の制約が無い。存在しないコードを書いても
-- account_map_covers_lines は「入力側に対応があるか」しか見ないため素通りし、
-- 配布物の master_* が null のまま静かに欠ける。
with map as (
    select * from {{ ref('account_map') }} where master_kan_code is not null
),

master_kan as (
    select distinct direction, kan_code from {{ ref('account_master') }}
),

master_kou as (
    select distinct direction, kan_code, kou_code from {{ ref('account_master') }}
)

select m.jurisdiction_code, m.direction, m.kan_code, m.kou_name,
       m.master_kan_code, m.master_kou_code,
       '参照先がマスタに無い' as problem
from map as m
left join master_kan as k on k.direction = m.direction and k.kan_code = m.master_kan_code
left join master_kou as u
    on u.direction = m.direction and u.kan_code = m.master_kan_code and u.kou_code = m.master_kou_code
where k.kan_code is null
   or (m.master_kou_code is not null and u.kou_code is null)
