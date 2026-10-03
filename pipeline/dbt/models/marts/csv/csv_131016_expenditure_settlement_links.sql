{{ fiscal_csv('131016', 'expenditure_settlement_links') }}
select l.* from {{ ref('fiscal_expenditure_settlement_links') }} l join {{ ref('fiscal_expenditure_budget_items') }} i using(budget_item_id) where i.jurisdiction_code='131016'
