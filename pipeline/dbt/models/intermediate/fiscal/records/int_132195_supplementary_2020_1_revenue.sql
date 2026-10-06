select *,'132195:2020:revenue:supplementary:55b99cec58e42222cfdd93d59821ab92d25464f23f2fcead40d0e19a3f17492a:saiin-saishutsu-hosei-1-revenue' dataset_id,
       null::varchar phase, 'unconfirmed' approval_status
from {{ ref('stg_132195__supplementary_2020_1_revenue') }}
