-- **総務省統計との突合で、説明できない差分を残さない。**
-- verdict='unexplained' の行が出るのは、帳簿側の畳み方か参照値かの
-- どちらかが壊れたとき。新しい差分は soumu_expected_diffs に分類を書いて受け止める。
--
-- ⚠️ **参照データが空でも通ってしまわないように。** 検査が空振りするのを
-- 避けるため、参照があるのに fudoki 側の行が1つも無い場合も落とす。
select jurisdiction_code, fiscal_year, scope, kan_label,
       our_yen, reference_yen, diff_yen, 'unexplained' as problem
from {{ ref('core_soumu_reconciliation') }}
where verdict = 'unexplained'

union all

select jurisdiction_code, fiscal_year, scope, '(fudoki側の行が無い)',
       null, null, null, 'no-data'
from (
    select jurisdiction_code, cast(fiscal_year as integer) as fiscal_year, scope
    from {{ ref('soumu_reference') }}
    group by all
) as r
where not exists (
    select 1 from {{ ref('core_soumu_reconciliation') }} as c
    where c.jurisdiction_code = r.jurisdiction_code
      and c.fiscal_year = r.fiscal_year
      and c.scope = r.scope
      and c.our_yen is not null
)
