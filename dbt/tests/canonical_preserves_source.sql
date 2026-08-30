-- **原典との多重集合一致。** 行数だけでなく中身の集合が一致すること。
-- 行数が合っていても取り違えや重複があれば落ちる。
-- staging で trim しているので、原典側も trim して比べる（三鷹市は差が3セルと実測済み）。
--
-- 比べる列は宣言から作る（`budget_source_columns` と `budget_amounts`）。
-- ⚠️ **階層だけでなく、追加の同一性の列と全部の金額も入れる。**
-- 狛江市は所属と予算区分まで含めて初めて行が一意になり、金額は1行に3つある。
-- 一部の列だけで比べると、取り違えが打ち消し合って通ってしまう。
with raw_cells as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, [
        {%- for c in var('budget_source_columns')[code][direction]
              + var('budget_extra_key_source_columns')[code][direction] %}
        {{ trim_cell('"' ~ c ~ '"') }},
        {%- endfor %}
        {#-
          ⚠️ **原典の金額の列名は年度で割れうる。** 多摩市の令和7年度は `合計 / 予算額` で、
          それ以前は `予算額` である。列を並べるのではなく年度で選ぶ（並べると、
          その年度に存在しない側が NULL のまま cells に入り、staging と一致しなくなる）。
        -#}
        {%- for name in budget_amount_names(code, direction) %}
        {{ budget_amount_source_sql(code, direction, name, 'year', cast_bigint=false) }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    ] as cells
    from {{ source('raw_' ~ code, direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
staged_cells as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, direction, [
        {%- for lv in var('budget_levels')[code][direction] %}
        {{ lv }}_source,
        {%- endfor %}
        {%- for k in var('budget_extra_key_columns')[code][direction] %}
        {{ k }}_source,
        {%- endfor %}
        {%- for name in budget_amount_names(code, direction) %}
        cast({{ name }} as varchar){% if not loop.last %},{% endif %}
        {%- endfor %}
    ] as cells
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
counted as (
    select jurisdiction, direction, cells, count(*) as n from raw_cells group by 1, 2, 3
    union all
    select jurisdiction, direction, cells, -count(*) from staged_cells group by 1, 2, 3
)
select jurisdiction, direction, cells, sum(n) as 差
from counted group by 1, 2, 3 having sum(n) <> 0
