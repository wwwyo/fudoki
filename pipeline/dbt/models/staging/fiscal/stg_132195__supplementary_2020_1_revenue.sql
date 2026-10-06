{{ config(materialized='view') }}
select source_row::bigint source_row, kind::varchar kind, direction::varchar direction,
       kan_code::varchar kan_code, kou_code::varchar kou_code, moku_code::varchar moku_code,
       moku_label::varchar moku_label, setsu_code::varchar setsu_code,
       setsu_label::varchar setsu_label, setsu_level::varchar setsu_level,
       setsu_x::bigint setsu_x, block_id::varchar block_id, before_amt::bigint before_amt,
       delta::bigint delta, total::bigint total, natl::bigint natl, metro::bigint metro,
       bond::bigint bond, other::bigint other, general::bigint general,
       physical_page::bigint physical_page, raw_text::varchar raw_text
from {{ source('raw_132195_supplementary_2020_1', 'data') }}
where direction_p = 'revenue' or direction_p is null
