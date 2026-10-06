{{ config(materialized='table') }}
select d.* exclude(phases_json), h.amendment_number, h.effective_at,
       case when json_extract_string(d.source_json,'$.provider')='mitaka-initial2026' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='tama-ordinary-history' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='ingestion.fiscal.komae_supplementary_2020_1_provider' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.namespace')='akishima-supplementary2020-2025' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.namespace')='akishima-initial445' and json_extract_string(d.source_json,'$.nonadditive')='true' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='akishima-settlement2024' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='akishima-settlement2020-2023' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='tama-native-settlement' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='tama-pre2020' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='chiyoda2025-native' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='chiyoda2021-settlement-native' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='ingestion.fiscal.komae_recovered_provider' and d.phases_json='[]' then cast(null as varchar)
            when json_extract_string(d.source_json,'$.provider')='akishima-settlement2019' and d.phases_json='[]' then cast(null as varchar)
            when d.document_kind='settlement' then 'executed' when d.document_kind='budget' then 'initial' else 'supplementary' end as source_amount_kind,
       '{"budgetHistory":"unconfirmed"}'::varchar as coverage_json
from {{ ref('int_fiscal_datasets') }} d
left join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h using(dataset_id)
order by dataset_id
