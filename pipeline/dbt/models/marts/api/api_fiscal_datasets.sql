{{ api_model('fiscal_datasets') }}
with lines as (
{% for code, direction in fiscal_units() %}
select dataset_id, jurisdiction_code, fiscal_year, direction, document_kind, origin_sha256, fiscal_line_id, fund_code, fund_label
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
), structure as (
{% for code, direction in fiscal_units() %}
select distinct dataset_id,
  '{{ {"hierarchy": var("fiscal_levels")[code][direction], "dimensions": var("fiscal_extra_key_columns")[code][direction]} | tojson }}' as structure_json
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
), funds as (
select dataset_id,
  cast(to_json(list(distinct struct_pack(code := coalesce(fund_code, ''), label := coalesce(fund_label, ''))
    order by struct_pack(code := coalesce(fund_code, ''), label := coalesce(fund_label, '')))) as varchar) as funds_json,
  count(*) as line_count
from lines group by dataset_id
), phases as (
select l.dataset_id, cast(to_json(list(distinct a.phase order by a.phase)) as varchar) as phases_json
from lines as l join {{ ref('api_amounts') }} as a using (fiscal_line_id)
group by l.dataset_id
)
select distinct l.dataset_id, l.jurisdiction_code, l.fiscal_year, l.direction, l.document_kind,
       l.origin_sha256, p.phases_json, d.source_json, cast(json_merge_patch(s.structure_json, json_object('funds', from_json(f.funds_json, '[{"code":"VARCHAR","label":"VARCHAR"}]'))) as varchar) as structure_json, f.line_count
from lines as l
join phases as p using (dataset_id)
join structure as s using (dataset_id)
join funds as f using (dataset_id)
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') as d
using (jurisdiction_code, fiscal_year, direction, document_kind)
order by dataset_id
