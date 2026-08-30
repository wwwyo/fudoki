-- **規則そのものの形を見る。** `cofog_invariants` は割り当てた**結果**しか見ていない。
--
-- 結果の検査は「階層が食い違っていないか」を問うので、`04.5.1.9` のような
-- 存在しない深さや `99` のような値域外は、分解した結果が整合してさえいれば通ってしまう
-- （`04.5.1.9` は division 04 / group 04.5 / class は空、で矛盾しない）。
-- 入力の誤りは入力で止めるほうが、原因に近いところで気づける。
--
-- ⚠️ **`decided_at_level` と粒度の対応は見ない。** 「款で決まったら division」ではない —
-- 商工費は款の名称だけで 04.7（group）まで決まる。科目のどの階層で決まったかと、
-- COFOG のどの深さまで決まるかは独立した2つの問いである。
with rules as (
    select priority, rule_id, status, coalesce(cofog_code, '') as cofog_code
    from {{ ref('cofog_rules') }}
)

-- 1. 形式。division は2桁、その下は `.数字` を2段まで
select 'COFOG コードの形式が不正' as problem, rule_id, cofog_code
from rules
where cofog_code <> '' and not regexp_full_match(cofog_code, '\d{2}(\.\d+){0,2}')

union all

-- 2. 値域。COFOG のディビジョンは 01〜10 の10個しかない
select 'ディビジョンが値域外', rule_id, cofog_code
from rules
where cofog_code <> ''
  and split_part(cofog_code, '.', 1) not in ('01','02','03','04','05','06','07','08','09','10')

union all

-- 3. 状態との整合。**割り当てたと言うなら割当先がある。**
--    分類不能・対象外は割当先を持たない（持っていたら状態のほうが誤っている）
select '割当済みなのに COFOG コードが空', rule_id, cofog_code
from rules where status = 'assigned' and cofog_code = ''

union all

select '割当済みでないのに COFOG コードが入っている', rule_id, cofog_code
from rules where status <> 'assigned' and cofog_code <> ''

union all

-- 4. 順序が決定的であること。**同じ priority が2本あると、当たる規則が実行ごとに変わりうる**
--    （規則は priority の順に見て最初に当たったものを採る）
select 'priority が重複している', cast(priority as varchar), cast(count(*) as varchar)
from rules group by priority having count(*) > 1
