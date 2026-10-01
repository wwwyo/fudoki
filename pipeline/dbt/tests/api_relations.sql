select 'line_without_dataset' as problem, l.fiscal_line_id as id
from {{ ref('api_fiscal_lines') }} as l left join {{ ref('api_fiscal_datasets') }} as d using (dataset_id)
where d.dataset_id is null
union all
select 'dataset_without_release_jurisdiction', d.dataset_id
from {{ ref('api_fiscal_datasets') }} as d left join {{ ref('api_release_jurisdictions') }} as j using (jurisdiction_code)
where j.jurisdiction_code is null
union all
select 'snapshot_without_master', j.jurisdiction_code
from {{ ref('api_release_jurisdictions') }} as j left join {{ ref('api_jurisdictions') }} as m using (jurisdiction_code)
where m.jurisdiction_code is null
union all
select 'duplicate_jurisdiction_master', jurisdiction_code
from {{ ref('api_jurisdictions') }} group by jurisdiction_code having count(*) != 1
union all
select 'unresolved_cofog_code', l.fiscal_line_id
from {{ ref('api_fiscal_lines') }} as l left join {{ ref('api_cofog_codes') }} as c on c.code=l.cofog_code
where (l.cofog_status='assigned' and (l.cofog_code is null or c.code is null))
   or (l.cofog_status!='assigned' and l.cofog_code is not null)
union all
select 'line_without_primary_amount', fiscal_line_id
from {{ ref('api_amounts') }} group by fiscal_line_id having sum(is_primary) != 1
union all
select 'duplicate_line', fiscal_line_id from {{ ref('api_fiscal_lines') }} group by fiscal_line_id having count(*) != 1
union all
select 'fund_code_has_multiple_labels', dataset_id || ':' || fund_code
from {{ ref('api_fiscal_lines') }} group by dataset_id, fund_code having count(distinct fund_label) != 1
