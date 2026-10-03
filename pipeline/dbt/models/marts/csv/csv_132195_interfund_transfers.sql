{{ fiscal_csv('132195', 'interfund_transfers') }}
select * from {{ ref('pkg_132195__interfund_transfers') }}
