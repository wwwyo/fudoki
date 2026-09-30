-- **kou_code で書いた項の対応は、実際の科目行に当たっているか。**
-- 項名が無い団体は項コードで写像するが、コードの書き間違いは名称と違って
-- 結合が静かに空振りする。宣言した対応が1行にも当たらないなら、
-- 対応表の行自体が嘘になっているので止める。
select m.jurisdiction_code, m.direction, m.fund, m.kan_code, m.kou_code,
       '項コードの対応が科目行に当たらない' as problem
from {{ ref('account_map') }} as m
where nullif(m.kou_code, '') is not null
  and not exists (
      select 1 from {{ ref('core_fiscal_accounts') }} as a
      where a.jurisdiction_code = m.jurisdiction_code
        and a.direction = m.direction
        and coalesce(m.fund, '一般会計') = a.canonical_fund
        and a.kan_code = m.kan_code
        and a.kou_code = m.kou_code
        and nullif(a.kou_name, '') is null
        and (nullif(m.fiscal_year_from, '') is null or a.fiscal_year >= cast(m.fiscal_year_from as integer))
        and (nullif(m.fiscal_year_to, '')   is null or a.fiscal_year <= cast(m.fiscal_year_to   as integer))
  )
