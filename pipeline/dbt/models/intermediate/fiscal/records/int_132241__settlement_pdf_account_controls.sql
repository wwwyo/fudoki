-- Independent original grain; no allocation or joins across legal and funding breakdowns.
select s.*, d.source_json,
       s.grain as line_granularity,
       'unconfirmed' as project_setsu_linkage,
       false as additive_within_own_grain,
       'unconfirmed' as cofog_status,
       case when (source_amount_unit='円' and unit_multiplier=1) or (source_amount_unit='千円' and unit_multiplier=1000)
            then source_amount * unit_multiplier else error('Unsupported Tama observed amount unit') end as amount,
       'JPY' as currency, fd.canonical_fund
from {{ ref('stg_132241__settlement_pdf_account_controls') }} s
join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/sources.json') d using(dataset_id)
left join {{ ref('fund_directory') }} fd
  on fd.jurisdiction_code=s.jurisdiction_code and fd.fund_label=s.fund_label
