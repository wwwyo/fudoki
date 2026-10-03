{{ fiscal_csv('132195', 'revenue_settlement_links') }}
select l.* from {{ ref('fiscal_revenue_settlement_links') }} l join {{ ref('fiscal_revenue_budget_items') }} i using(budget_item_id) where i.jurisdiction_code='132195'
