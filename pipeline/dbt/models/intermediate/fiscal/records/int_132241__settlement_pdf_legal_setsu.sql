-- Independent original grain; no allocation or joins across legal and funding breakdowns.
select s.*, d.source_json,
       s.grain as line_granularity,
       'unconfirmed' as project_setsu_linkage,
       true as additive_within_own_grain,
       'unconfirmed' as cofog_status,
       case when (source_amount_unit='円' and unit_multiplier=1) or (source_amount_unit='千円' and unit_multiplier=1000)
            then source_amount * unit_multiplier else error('Unsupported Tama observed amount unit') end as amount,
       'JPY' as currency, fd.canonical_fund,
       ms.expenditure_setsu_id,
       case when ms.expenditure_setsu_id is null then 'unconfirmed' else 'mapped' end as setsu_mapping_status
from {{ ref('stg_132241__settlement_pdf_legal_setsu') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d using(dataset_id)
left join {{ ref('fund_directory') }} fd
  on fd.jurisdiction_code=s.jurisdiction_code and fd.fund_label=s.fund_label
left join {{ ref('expenditure_setsu_map') }} m
  on m.jurisdiction_code=s.jurisdiction_code and m.setsu_label=s.setsu_label
left join {{ ref('fiscal_expenditure_setsu_master') }} def
  on def.expenditure_setsu_id=m.expenditure_setsu_id
left join {{ ref('fiscal_expenditure_setsu_master') }} ms
  on ms.label=def.label and cast(ms.code as integer)=cast(s.setsu_code as integer)
 and s.fiscal_year>=coalesce(ms.valid_from_fiscal_year,-9999)
 and s.fiscal_year<=coalesce(ms.valid_to_fiscal_year,9999)
