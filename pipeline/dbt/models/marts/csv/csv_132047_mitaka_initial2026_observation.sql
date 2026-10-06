{{ fiscal_csv('132047', 'mitaka_initial2026_observation') }}
select * from {{ ref('mart_mitaka_initial2026') }}
