-- **対応表の参照先がマスタに実在するか。**
--
-- account_map の master_kan_code / master_kou_code はマスタへの外部キーだが、
-- seed どうしなので DB の制約が無い。存在しないコードを書いても
-- account_map_covers_lines は「入力側に対応があるか」しか見ないため素通りし、
-- 配布物の master_* が null のまま静かに欠ける。
with map as (
    -- ⚠️ master_kan_code が無いのに master_kou_code だけある行も不正（親の無い項参照）。
    -- kan で絞ってから見ると、その形の行が検査を素通りする。
    select * from {{ ref('account_map') }}
    where master_kan_code is not null or master_kou_code is not null
),

-- どのマスタを引くかは対応の fund で決まる。空（一般会計）は地方自治法施行規則の
-- 別記、特別会計は会計固有の調査票の勘定科目。
master_kan as (
    select '一般会計' as fund, direction, kan_code
    from (select distinct direction, kan_code from {{ ref('account_master') }})
    union all
    select canonical_fund, direction, kan_code from {{ ref('special_account_master') }}
),

master_kou as (
    select '一般会計' as fund, direction, kan_code, kou_code
    from (select distinct direction, kan_code, kou_code from {{ ref('account_master') }})
)

select m.jurisdiction_code, m.direction, m.fund, m.kan_code, m.kou_name,
       m.master_kan_code, m.master_kou_code,
       '参照先がマスタに無い' as problem
from map as m
left join master_kan as k
    on k.fund = coalesce(m.fund, '一般会計')
    and k.direction = m.direction and k.kan_code = m.master_kan_code
left join master_kou as u
    on u.fund = coalesce(m.fund, '一般会計')
    and u.direction = m.direction and u.kan_code = m.master_kan_code and u.kou_code = m.master_kou_code
where k.kan_code is null
   or (m.master_kou_code is not null and u.kou_code is null)
