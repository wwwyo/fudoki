with allocations as (
    select *, '一般会計' as account_name
    from {{ source('raw_131024_settlement', 'chuo-general-reserve-transfers') }}
    union all
    select *, '介護保険事業会計' as account_name
    from {{ source('raw_131024_settlement', 'chuo-care-reserve-transfers') }}
)

select
    * exclude (jurisdiction, year, edition, "table", file_row_number),
    cast(jurisdiction as varchar) as jurisdiction_code,
    cast(year as integer) as fiscal_year,
    edition as origin_sha256,
    "table" as source_table_id,
    file_row_number + 1 as source_row,
    "充用先_事業" as destination_project,
    cast(replace(regexp_replace("充用先_金額", ' 円$', ''), ',', '') as bigint) as allocated_amount
from allocations
