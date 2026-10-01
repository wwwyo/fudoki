{{ fiscal_distribution_csv('132047', 'revenue_settlement_links') }}
select l.* from {{ ref('api_fiscal_revenue_settlement_links') }} l join {{ ref('api_fiscal_revenue_budget_items') }} i using(budget_item_id) where i.jurisdiction_code='132047'
