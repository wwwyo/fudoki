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
from lines as l join {{ ref('int_fiscal_amounts') }} as a using (fiscal_line_id)
group by l.dataset_id
)
select distinct l.dataset_id, l.jurisdiction_code, l.fiscal_year, l.direction, l.document_kind,
       l.origin_sha256, p.phases_json, d.source_json, cast(json_merge_patch(s.structure_json, json_object('funds', from_json(f.funds_json, '[{"code":"VARCHAR","label":"VARCHAR"}]'))) as varchar) as structure_json, f.line_count
from lines as l
join phases as p using (dataset_id)
join structure as s using (dataset_id)
join funds as f using (dataset_id)
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') as d
using (dataset_id)
union all
select h.dataset_id, h.jurisdiction_code, h.fiscal_year, h.direction, h.document_kind, h.origin_sha256,
       case when h.document_kind='budget' then '["approved"]' else '["adjusted"]' end as phases_json,
       h.source_json, h.structure_json, h.line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h
-- Recovered chapters are registered below with their unconfirmed phase.
where coalesce(json_extract_string(h.source_json, '$.provider'), '')
      not in ('ingestion.fiscal.komae_recovered_provider', 'ingestion.fiscal.komae_supplementary_2020_1_provider',
              'ingestion.fiscal.chiyoda_budget_changes')
  and coalesce(json_extract_string(h.source_json, '$.namespace'), '') != 'chiyoda-supplementary-native'
union all
-- Independently observed Tama settlement breakdowns and nonadditive proof.
-- Registration does not union their values into generic fiscal amounts.
select t.dataset_id, cast(t.jurisdiction_code as varchar), cast(t.fiscal_year as integer),
       cast(t.direction as varchar), cast(t.document_kind as varchar), cast(t.origin_sha256 as varchar),
       case when t.observation_role='source-words' then '[]' else '["executed"]' end as phases_json,
       cast(t.source_json as varchar),
       cast(json_object(
           'hierarchy', case
               when t.observation_role='legal-setsu' then ['fund','kan','kou','moku','setsu']
               when t.observation_role='project-funding' then ['fund','kan','kou','moku','project','funding']
               when t.observation_role='project-controls' then ['fund','kan','kou','moku','project']
               when t.observation_role='moku-controls' then ['fund','kan','kou','moku']
               when t.observation_role='account-controls' then ['fund'] else [] end,
           'dimensions', [],
           'funds', case when t.fund_label='' then []
                         else [struct_pack(code := '', label := t.fund_label)] end,
           'scope', json_object('granularity',t.grain,'observationRole',t.observation_role,
                'independentBreakdown',true,'additiveWithinOwnGrain',t.additive_within_own_grain,
                'financialLeaf',t.additive_within_own_grain,'nonadditive',not t.additive_within_own_grain,
                'sourceAmountUnit',t.source_amount_unit,'unitMultiplier',t.unit_multiplier,
                'projectSetsuLinkage','unconfirmed')) as varchar) as structure_json,
       cast(t.observation_count as bigint) as line_count
from {{ ref('int_132241__settlement_pdf_datasets') }} t
union all
-- FY2020 native-scan role datasets; controls/words/pages never enter fiscal amounts.
select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,
       phases_json,source_json,structure_json,line_count
from {{ ref('int_132241__tama_native_settlement_datasets') }}
union all
select * from {{ ref('int_132071_initial445_datasets') }}
union all
-- FY2024 recognized settlement datasets; controls/projects/pages never enter fiscal amounts.
select * from {{ ref('int_132071_settlement2024_datasets') }}

union all
-- FY2020-2023 recognized settlement datasets; controls/projects/pages never enter fiscal amounts.
select * from {{ ref('int_132071_settlement2020_2023_datasets') }}

union all

-- pre-FY2020 recovered role datasets; controls/lexical/words/pages never enter fiscal amounts.
select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,
       phases_json,source_json,structure_json,line_count
from {{ ref('int_132241__tama_pre2020_datasets') }}
union all
-- FY2025 Chiyoda native-scan role datasets; all grain breakdowns stay nonadditive, phase NULL.
select * from {{ ref('int_native__datasets') }}
union all
-- Recovered Komae FY2019-22 initial-detail candidates; phases=[], non-additive.
-- Global NULL guard: only NULL-phase rows may enter the union.
select * from {{ ref('int_132195_recovered_datasets') }} where phases_json='[]'
union all
-- FY2019 Akishima settlement; controls/projects/pages/revenue stay nonadditive observations.
select * from {{ ref('int_132071_settlement2019_datasets') }}
union all
-- Finite Akishima FY2025 No.1 selected kan-summary observations; noncanonical phases.
select * from {{ ref('int_132071_supplementary_fy2025_01_datasets') }}
union all
-- FY2021 Chiyoda settlement native-scan role datasets; all grain breakdowns stay nonadditive, phase NULL.
select * from {{ ref('int_native_settle__datasets') }}

union all
-- Mitaka mixed printed observations remain nonadditive, phases=[]; exact source guard is in the dedicated model.
select dataset_id,jurisdiction_code,fiscal_year,direction,document_kind,origin_sha256,phases_json,source_json,structure_json,line_count
from {{ ref('int_132047__mitaka_initial2026_datasets') }}

union all
-- Ordinary history original observations; lexical phases=[], no generic amount union.
select * from {{ ref('int_132241__tama_ordinary_history_datasets') }}
union all
-- Komae FY2020 supplementary1: printed observations only, phase remains NULL/[]; never fiscal amounts.
select h.dataset_id,h.jurisdiction_code,h.fiscal_year,h.direction,h.document_kind,h.origin_sha256,
       '[]'::varchar phases_json,h.source_json,h.structure_json,h.line_count
from read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h
where json_extract_string(h.source_json,'$.provider')='ingestion.fiscal.komae_supplementary_2020_1_provider'

union all
select * from {{ ref('int_132241__initial_native_datasets') }}
union all
select * from {{ ref('int_131016__supplementary_native_datasets') }}
order by dataset_id
