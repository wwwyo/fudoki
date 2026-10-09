with text_cases(raw, expected) as (
    values
        ('　ﾎｹﾝ（Ａ）　', 'ホケン(A)'),
        ('①事業', '1事業'),
        (chr(9) || 'e' || chr(769) || chr(10), 'é'),
        ('事業 内訳', '事業 内訳'),
        (null, null)
), amount_cases(raw, expected) as (
    values
        ('　５，７２０，０００　円　', 5720000::bigint),
        ('62,239,000円', 62239000::bigint),
        ('△１，２００', -1200::bigint),
        ('−1,200', -1200::bigint),
        ('0', 0::bigint),
        (null, null)
)
select 'text' as kind, raw
from text_cases
where {{ trim_cell('raw') }} is distinct from expected
union all
select 'amount' as kind, raw
from amount_cases
where {{ staging_amount('raw') }} is distinct from expected
