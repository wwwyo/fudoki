select fiscal_line_id, 'hierarchy' as name_kind, level, label as value, name_source, '' as basis
from {{ ref('int_fiscal_line_hierarchy') }} where label != ''
union all
select s.fiscal_line_id, 'project' as name_kind, 'daijigyo' as level, p.project_name as value,
       'judgment' as name_source, p.match_basis as basis
-- 狛江市の事業名称の対応は大事業コードまでの専用キーであり、他団体の異なる科目体系へ流用しない。
from {{ ref('stg_132195__expenditure') }} as s
join {{ ref('core_fiscal_project_names') }} as p
using (jurisdiction_code, fiscal_year, fund_code, kan_code, kou_code, moku_code, daijigyo_code)
union all
select fiscal_line_id, 'dimension' as name_kind, dimension as level, label as value,
       'canonical' as name_source, '' as basis
from {{ ref('int_fiscal_line_dimensions') }} where label != ''
order by fiscal_line_id, name_kind, level
