select 'line_without_dataset' as problem, l.fiscal_line_id as id
from {{ ref('int_fiscal_lines') }} as l left join {{ ref('int_fiscal_datasets') }} as d using (dataset_id)
where d.dataset_id is null
union all
select 'dataset_without_release_jurisdiction', d.dataset_id
from {{ ref('int_fiscal_datasets') }} as d left join {{ ref('int_fiscal_jurisdiction_metadata') }} as j using (jurisdiction_code)
where j.jurisdiction_code is null
union all
select 'snapshot_without_master', j.jurisdiction_code
from {{ ref('int_fiscal_jurisdiction_metadata') }} as j left join {{ ref('jurisdiction_master') }} as m using (jurisdiction_code)
where m.jurisdiction_code is null
union all
select 'duplicate_jurisdiction_master', jurisdiction_code
from {{ ref('jurisdiction_master') }} group by jurisdiction_code having count(*) != 1
union all
select 'unresolved_cofog_code', l.fiscal_line_id
from {{ ref('int_fiscal_lines') }} as l left join {{ ref('cofog_master') }} as c on c.code=l.cofog_code
where (l.cofog_status='assigned' and (l.cofog_code is null or c.code is null))
   or (l.cofog_status!='assigned' and l.cofog_code is not null)
union all
select 'line_without_primary_amount', fiscal_line_id
from {{ ref('int_fiscal_amounts') }} group by fiscal_line_id having sum(is_primary) != 1
union all
select 'duplicate_line', fiscal_line_id from {{ ref('int_fiscal_lines') }} group by fiscal_line_id having count(*) != 1
union all
select 'fund_code_has_multiple_labels', dataset_id || ':' || fund_code
from {{ ref('int_fiscal_lines') }}
-- 会計名称しかない原典の空コードは、共通の会計を表すコードではない。
-- その原典は名称で識別し、印字されたコードだけにコード→名称の一意性を要求する。
where nullif(fund_code, '') is not null
group by dataset_id, fund_code having count(distinct fund_label) != 1
