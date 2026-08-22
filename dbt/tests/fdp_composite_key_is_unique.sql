-- **FDP の複合主キーが一意であること。**
-- budget_line_id はハッシュなので、衝突していないことを別の経路でも確かめる。
-- 階層のコードを全部並べたものが一意なら、識別子の導出が壊れていても検出できる。
select 'expenditure' as direction, key, n from (
    select fund_code || '/' || kan_code || '/' || kou_code || '/' || moku_code || '/' || jikou_code
        || '/' || setsu_code || '/' || saisaisetsu_code || '/' || fund_label || kan_label || kou_label
        || moku_label || jikou_label || setsu_label || saisaisetsu_label as key, count(*) as n
    from {{ ref('stg_132047__expenditure') }} group by 1 having count(*) > 1
)
union all
select 'revenue', key, n from (
    select fund_code || '/' || kan_code || '/' || kou_code || '/' || moku_code || '/' || setsu_code
        || '/' || saisetsu_code || '/' || saisaisetsu_code || '/' || fund_label || kan_label || kou_label
        || moku_label || setsu_label || saisetsu_label || saisaisetsu_label as key, count(*) as n
    from {{ ref('stg_132047__revenue') }} group by 1 having count(*) > 1
)
