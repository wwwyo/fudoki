select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,amount from {{ ref('distribution_131016_settlement_expenditure') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_131016_settlement_expenditure') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_131016_settlement_expenditure_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_131016_settlement_expenditure_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,amount from {{ ref('distribution_131016_settlement_revenue') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_131016_settlement_revenue') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,amount from {{ ref('distribution_131016_initial_expenditure_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_131016_initial_expenditure_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_131016_initial_expenditure_budget_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_131016_initial_expenditure_budget_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016') except (select fiscal_line_id,amount from {{ ref('distribution_131016_initial_revenue_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_131016_initial_revenue_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='131016'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,amount from {{ ref('distribution_132047_settlement_expenditure') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132047_settlement_expenditure') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132047_settlement_expenditure_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132047_settlement_expenditure_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,amount from {{ ref('distribution_132047_settlement_revenue') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132047_settlement_revenue') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,amount from {{ ref('distribution_132047_initial_expenditure_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132047_initial_expenditure_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132047_initial_expenditure_budget_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132047_initial_expenditure_budget_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047') except (select fiscal_line_id,amount from {{ ref('distribution_132047_initial_revenue_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132047_initial_revenue_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132047'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,amount from {{ ref('distribution_132071_settlement_expenditure') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132071_settlement_expenditure') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132071_settlement_expenditure_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132071_settlement_expenditure_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,amount from {{ ref('distribution_132071_settlement_revenue') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132071_settlement_revenue') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,amount from {{ ref('distribution_132071_initial_expenditure_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132071_initial_expenditure_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132071_initial_expenditure_budget_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132071_initial_expenditure_budget_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071') except (select fiscal_line_id,amount from {{ ref('distribution_132071_initial_revenue_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132071_initial_revenue_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132071'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,amount from {{ ref('distribution_132195_settlement_expenditure') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132195_settlement_expenditure') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132195_settlement_expenditure_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132195_settlement_expenditure_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,amount from {{ ref('distribution_132195_settlement_revenue') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132195_settlement_revenue') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,amount from {{ ref('distribution_132195_initial_expenditure_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132195_initial_expenditure_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132195_initial_expenditure_budget_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132195_initial_expenditure_budget_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195') except (select fiscal_line_id,amount from {{ ref('distribution_132195_initial_revenue_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132195_initial_revenue_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132195'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,amount from {{ ref('distribution_132241_settlement_expenditure') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132241_settlement_expenditure') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132241_settlement_expenditure_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132241_settlement_expenditure_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_settlement_expenditure_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,amount from {{ ref('distribution_132241_settlement_revenue') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132241_settlement_revenue') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_settlement_revenue_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,amount from {{ ref('distribution_132241_initial_expenditure_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132241_initial_expenditure_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132241_initial_expenditure_budget_cofog') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,cofog_code,cofog_status,cofog_basis,consolidation,counterpart_fund from {{ ref('distribution_132241_initial_expenditure_budget_cofog') }}) except (select l.fiscal_line_id,l.cofog_code,l.cofog_status,l.cofog_basis,l.consolidation,l.counterpart_fund from {{ ref('api_fiscal_initial_expenditure_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
union all
select fiscal_line_id from ((select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241') except (select fiscal_line_id,amount from {{ ref('distribution_132241_initial_revenue_budget') }}))
union all
select fiscal_line_id from ((select fiscal_line_id,amount from {{ ref('distribution_132241_initial_revenue_budget') }}) except (select l.fiscal_line_id,l.amount from {{ ref('api_fiscal_initial_revenue_budget_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id) where d.jurisdiction_code='132241'))
