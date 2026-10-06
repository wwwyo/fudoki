-- 同じ予算を目×節で分解した独立した観測。事業への配分・右頁との結合は行わない。
select s.*, fd.canonical_fund,
       case when s.source_amount_unit = '千円' then s.source_amount * 1000
            else error('Unsupported independent setsu amount unit') end as amount,
       'approved' as phase, 'independent-moku-setsu' as line_granularity,
       'unconfirmed' as project_setsu_linkage,
       ms.expenditure_setsu_id,
       case when ms.expenditure_setsu_id is null then 'unconfirmed' else 'mapped' end as setsu_mapping_status,
       json_extract_string(d.source_json, '$.explanationDatasetId') as explanation_dataset_id,
       d.source_json
from {{ ref('stg_131016__moku_setsu') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d using(dataset_id)
left join {{ ref('fund_directory') }} fd
  on fd.jurisdiction_code=s.jurisdiction_code and fd.fund_label=s.fund_label
left join {{ ref('expenditure_setsu_map') }} m
  on m.jurisdiction_code=s.jurisdiction_code and m.setsu_label=s.setsu_label
left join {{ ref('fiscal_expenditure_setsu_master') }} def
  on def.expenditure_setsu_id=m.expenditure_setsu_id
left join {{ ref('fiscal_expenditure_setsu_master') }} ms
  on ms.label=def.label and cast(ms.code as integer)=cast(s.setsu_code as integer)
 and s.fiscal_year >= coalesce(ms.valid_from_fiscal_year, -9999)
 and s.fiscal_year <= coalesce(ms.valid_to_fiscal_year, 9999)
