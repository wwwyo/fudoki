select 'line_without_dataset' as problem, l.fiscal_line_id as id
from {{ ref('api_fiscal_lines') }} as l left join {{ ref('api_fiscal_datasets') }} as d using (dataset_id)
where d.dataset_id is null
union all
select 'line_without_classification', l.fiscal_line_id
from {{ ref('api_fiscal_lines') }} as l left join {{ ref('api_cofog') }} as c using (fiscal_line_id)
where c.fiscal_line_id is null
union all
select 'line_without_primary_amount', fiscal_line_id
from {{ ref('api_amounts') }} group by fiscal_line_id having sum(is_primary) != 1
union all
select 'duplicate_line', fiscal_line_id from {{ ref('api_fiscal_lines') }} group by fiscal_line_id having count(*) != 1
union all
select 'fund_code_has_multiple_labels', dataset_id || ':' || fund_code
from {{ ref('api_fiscal_lines') }} group by dataset_id, fund_code having count(distinct fund_label) != 1
