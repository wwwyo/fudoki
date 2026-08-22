{{ config(severity = 'warn') }}
-- **警告。落とさないが毎回見える。**
--
-- 原典のセルに前後の空白が入っていることを報告する。staging で trim しているので
-- 下流には影響しないが、**黙って直すと次に読んだ者が原典の状態を誤解する**。
-- TS 版はここを報告せずに trim しており、原典に全角スペースが入っていることを
-- 誰も知らないまま1団体目を配っていた。
--
-- 件数が増えたら原典側の入力運用が変わった合図でもある。
with cells as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, direction, source_row, unnest([
        {% for c in var('budget_source_columns')[code][direction]
              + var('budget_extra_key_source_columns')[code][direction] %}
        "{{ c }}"{% if not loop.last %},{% endif %}
        {% endfor %}
    ]) as cell
    from {{ source('raw_' ~ code, direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select jurisdiction, direction, source_row, cell, '前後に空白がある。staging で trim した' as note
from cells
where cell is not null and cell <> {{ trim_cell('cell') }}
