/**
 * # 検証
 *
 * **合計の突合だけに頼らない。** 1行の欠落と同額の行の重複は合計では相殺されて素通りする。
 * 再生成の一致も、同じ誤りが決定的に再現されることしか示さない。
 * そこで性質の異なる検査を並べ、どれか1つが通っても他が落ちる状態を作る。
 */
import { CUSTOM_COLUMN_TYPES } from './columns'
import type { DerivedTable } from './transform'
import type { CanonicalTable, FieldSpec, Row } from './load'
import { fdpCompositeKey } from './fdp'
import type { BudgetSource } from './source'
import { MITAKA_2024_PUBLISHED } from './published/mitaka-2024'
import taxonomy from './taxonomy/budget-taxonomy.json'
import { splitRows } from './extract'

export type Check = { name: string; ok: boolean; detail: string }

type ColumnTypeDef = { name: string; dataType: string; unique?: boolean; labelOf?: string; prior?: string }
const STANDARD: ColumnTypeDef[] = taxonomy.columnTypes
const CUSTOM: ColumnTypeDef[] = CUSTOM_COLUMN_TYPES.map(({ why: _why, ...d }) => d)
const ALL_TYPES = new Map<string, ColumnTypeDef>([...STANDARD, ...CUSTOM].map((d) => [d.name, d]))
export const UNIQUE_TYPES = new Set([...ALL_TYPES.values()].filter((d) => d.unique).map((d) => d.name))

/** 区切りに使う制御文字。名称にも金額にも現れないので、連結キーの衝突が起きない */
const SEP = "\u001f"

const yen = (n: number) => n.toLocaleString('ja-JP')

/**
 * 原典の全行が、欠落も重複もなく変換後に対応する。
 *
 * **合計ではなく多重集合として比べる。** 同じ内容の行が複数あることは正常なので、
 * 集合ではなく出現回数まで一致させる。
 */
function multisetMatch(sourceText: string, table: CanonicalTable): Check {
  const raw = splitRows(sourceText).slice(1)
  const tally = new Map<string, number>()
  for (const r of raw) tally.set(r.join(SEP), (tally.get(r.join(SEP)) ?? 0) + 1)

  const levels = table.levels
  for (const row of table.rows) {
    const key = [...levels.map((l) => String(row[`${l.key}_source`])), String(row.source_amount)].join(SEP)
    const n = tally.get(key)
    if (n === undefined) return { name: '原典との多重集合一致', ok: false, detail: `正本にあって原典に無い行がある: ${key.replace(new RegExp(SEP, "g"), ' | ')}` }
    if (n === 1) tally.delete(key)
    else tally.set(key, n - 1)
  }
  if (tally.size > 0) {
    const left = [...tally].slice(0, 3).map(([k, n]) => `${k.replace(new RegExp(SEP, "g"), ' | ')} ×${n}`)
    return { name: '原典との多重集合一致', ok: false, detail: `原典にあって正本に無い行が ${tally.size} 種: ${left.join(' / ')}` }
  }
  return { name: '原典との多重集合一致', ok: true, detail: `原典 ${raw.length} 行と正本 ${table.rows.length} 行が多重集合として一致` }
}

/** `code + label` を連結して原典のセルへ戻る。分離が可逆であることを見る */
function cellRoundTrip(table: CanonicalTable): Check {
  for (const row of table.rows) {
    for (const l of table.levels) {
      const joined = `${row[`${l.key}_code`]}${row[`${l.key}_label`]}`
      const source = String(row[`${l.key}_source`])
      if (joined !== source) {
        return { name: 'code + label が原文へ戻る', ok: false, detail: `原典 ${row.source_row} 行目 ${l.sourceColumn}: 「${joined}」≠「${source}」` }
      }
    }
  }
  return { name: 'code + label が原文へ戻る', ok: true, detail: `${table.rows.length} 行 × ${table.levels.length} 階層すべてで原文へ戻る` }
}

/** code から label が一意に定まり、子から親も一意に定まる */
function dependencies(table: CanonicalTable): Check[] {
  const out: Check[] = []

  // code → label（同じ親の下で、同じコードが違う名称を持たないこと）。
  // ⚠️ これは全階層で成り立つ性質ではない。三鷹市の歳出の細々節は同じ節の下でコードを再利用する。
  // そこで階層ごとの宣言（codeUniqueAmongSiblings）と実測を**両方向で**突き合わせる。
  const measured = new Map<string, { collisions: number; example: string }>()
  const codeToLabel = new Map<string, string>()
  for (const row of table.rows) {
    for (const [i, l] of table.levels.entries()) {
      const parent = table.levels.slice(0, i).map((p) => row[`${p.key}_source`]).join('/')
      const key = [l.key, parent, row[`${l.key}_code`]].join(SEP)
      const label = String(row[`${l.key}_label`])
      const seen = codeToLabel.get(key)
      if (seen === undefined) codeToLabel.set(key, label)
      else if (seen !== label) {
        const acc = measured.get(l.key) ?? { collisions: 0, example: `${l.sourceColumn} ${row[`${l.key}_code`]} が「${seen}」と「${label}」の両方に対応する` }
        acc.collisions++
        measured.set(l.key, acc)
      }
    }
  }

  const wrong: string[] = []
  for (const l of table.levels) {
    const m = measured.get(l.key)
    if (l.codeUniqueAmongSiblings && m) wrong.push(`${l.sourceColumn}: 一意と宣言しているが ${m.collisions} 箇所で衝突（${m.example}）`)
    if (!l.codeUniqueAmongSiblings && !m) wrong.push(`${l.sourceColumn}: 一意でないと宣言しているが実際は一意。宣言が古いか原典が直された`)
  }
  const declaredNonUnique = table.levels.filter((l) => !l.codeUniqueAmongSiblings)
  out.push({
    name: 'code → label の従属が階層ごとの宣言と一致',
    ok: wrong.length === 0,
    detail:
      wrong.length === 0
        ? `${codeToLabel.size} 個の（親, コード）を検査。` +
          (declaredNonUnique.length === 0
            ? '全階層でコードが兄弟間で一意'
            : declaredNonUnique.map((l) => `${l.sourceColumn}は兄弟間で一意でない（実測 ${measured.get(l.key)?.collisions ?? 0} 箇所。宣言どおり）`).join(' / ')) +
          '。識別子はコードではなくセル全文から導いているため、この性質があっても一意性は保たれる'
        : wrong.join(' / '),
  })

  // 子 → 親（完全修飾パスなので定義上一意。パスの作り方が壊れていないことを見る）
  const childToParent = new Map<string, string>()
  const orphans: string[] = []
  for (const row of table.rows) {
    for (let i = 1; i < table.levels.length; i++) {
      const path = table.levels.slice(0, i + 1).map((p) => row[`${p.key}_source`]).join('/')
      const parent = table.levels.slice(0, i).map((p) => row[`${p.key}_source`]).join('/')
      const seen = childToParent.get(path)
      if (seen === undefined) childToParent.set(path, parent)
      else if (seen !== parent && orphans.length < 5) orphans.push(`${path} が「${seen}」と「${parent}」の両方に属する`)
    }
  }
  out.push({
    name: '子 → 親が一意（任意の細々節から款まで辿れる）',
    ok: orphans.length === 0,
    detail: orphans.length === 0 ? `${childToParent.size} 個の階層ノードがそれぞれ1つの親を持つ` : orphans.join(' / '),
  })
  return out
}

/** 識別子の衝突。Load 段で例外にしているので、ここは0件であることの記録 */
function idCollisions(table: CanonicalTable): Check {
  const seen = new Set<string>()
  let dup = 0
  for (const r of table.rows) {
    const id = String(r.budget_line_id)
    if (seen.has(id)) dup++
    seen.add(id)
  }
  return { name: 'budget-line-id の衝突', ok: dup === 0, detail: dup === 0 ? `${seen.size} 件がすべて一意` : `${dup} 件が衝突` }
}

/** FDP の複合主キー（unique な ColumnType を持つ列の組）も重複しないこと */
function compositeKeyUnique(table: { fields: FieldSpec[]; rows: Row[] }, label: string): Check {
  const key = fdpCompositeKey(table.fields, UNIQUE_TYPES)
  const seen = new Set<string>()
  let dup = 0
  for (const r of table.rows) {
    const k = key.map((n) => String(r[n])).join(SEP)
    if (seen.has(k)) dup++
    seen.add(k)
  }
  return { name: `FDP の複合主キーが一意（${label}）`, ok: dup === 0, detail: dup === 0 ? `${key.length} 列の組 ${key.join(', ')} が ${seen.size} 件すべて一意` : `${dup} 件が重複` }
}

/** 円への正規化が桁あふれせず、原典の値と単位から復元できる */
function amountConversion(table: CanonicalTable, source: BudgetSource): Check {
  for (const r of table.rows) {
    const expected = Number(r.source_amount) * source.amountUnit.multiplier
    if (r.value !== expected || !Number.isSafeInteger(Number(r.value))) {
      return { name: '金額の円への正規化', ok: false, detail: `原典 ${r.source_row} 行目: ${r.source_amount}${source.amountUnit.label} → ${r.value}` }
    }
  }
  const total = table.rows.reduce((s, r) => s + Number(r.value), 0)
  return { name: '金額の円への正規化', ok: true, detail: `全 ${table.rows.length} 行が ×${source.amountUnit.multiplier}。合計 ${yen(total)} 円` }
}

/**
 * Data Package / Table Schema / FDP への適合。
 *
 * ⚠️ これは fudoki 自身の適合チェックであって、参照実装による検証ではない。
 * 仕様が正準と宣言する taxonomy の URL が 404 を返すため、
 * ColumnType の一覧はリポジトリに取り込んだ写し（src/budget/taxonomy/）を出所にしている。
 */
function descriptorConformance(descriptor: Record<string, unknown>): Check[] {
  const out: Check[] = []
  const errors: string[] = []

  if (descriptor.profile !== 'tabular-data-package') errors.push('package の profile が tabular-data-package でない')
  if (!/^([-a-z0-9._/])+$/.test(String(descriptor.name))) errors.push(`package の name「${descriptor.name}」が Data Package の命名規則に合わない`)
  const resources = descriptor.resources as { name: string; path: string; schema: { fields: { name: string; type: string; columnType?: string; labelOf?: string }[]; primaryKey: string[] } }[]
  if (!Array.isArray(resources) || resources.length === 0) errors.push('resources が無い')

  for (const r of resources) {
    if (!/^([-a-z0-9._/])+$/.test(r.name)) errors.push(`resource の name「${r.name}」が命名規則に合わない`)
    const names = new Set(r.schema.fields.map((f) => f.name))
    if (names.size !== r.schema.fields.length) errors.push(`${r.name}: 列名が重複している`)
    for (const pk of r.schema.primaryKey) if (!names.has(pk)) errors.push(`${r.name}: primaryKey の ${pk} が fields に無い`)
  }
  out.push({ name: 'Data Package / Table Schema への適合', ok: errors.length === 0, detail: errors.length === 0 ? `パッケージ1件・リソース ${resources.length} 件が構造要件を満たす` : errors.join(' / ') })

  // ColumnType が taxonomy に存在し、dataType と labelOf が宣言と整合するか
  const typeErrors: string[] = []
  for (const r of resources) {
    for (const f of r.schema.fields) {
      if (!f.columnType) continue
      const def = ALL_TYPES.get(f.columnType)
      if (!def) {
        typeErrors.push(`${r.name}.${f.name}: ColumnType「${f.columnType}」が標準にも独自定義にも無い`)
        continue
      }
      // Table Schema の integer / number と taxonomy の dataType を照合する
      if (def.dataType !== f.type && !(def.dataType === 'number' && f.type === 'integer')) {
        typeErrors.push(`${r.name}.${f.name}: 型が ${f.type} だが ColumnType は ${def.dataType} を要求する`)
      }
      if (def.labelOf && f.labelOf !== def.labelOf) typeErrors.push(`${r.name}.${f.name}: labelOf が ${f.labelOf} だが ColumnType は ${def.labelOf} を指す`)
      if (f.labelOf && !ALL_TYPES.has(f.labelOf)) typeErrors.push(`${r.name}.${f.name}: labelOf の指す ${f.labelOf} が存在しない`)
    }
  }
  out.push({
    name: 'FDP の ColumnType への適合',
    ok: typeErrors.length === 0,
    detail: typeErrors.length === 0 ? `標準 ${STANDARD.length} 件 + 独自 ${CUSTOM.length} 件の ColumnType と照合して不整合なし` : typeErrors.slice(0, 6).join(' / '),
  })
  return out
}

/** 会計ごとの歳出と歳入の一致。**三鷹市の当該年度に限った条件付き検算** */
function crossCheck(expenditure: CanonicalTable, revenue: CanonicalTable, source: BudgetSource): Check {
  if (!source.crossCheckExpenditureEqualsRevenue) {
    return { name: '歳出と歳入の交差検算', ok: true, detail: 'この取得元では成立が確認されていないため適用しない' }
  }
  const sum = (t: CanonicalTable) => {
    const m = new Map<string, number>()
    for (const r of t.rows) m.set(String(r.fund_source), (m.get(String(r.fund_source)) ?? 0) + Number(r.value))
    return m
  }
  const [e, r] = [sum(expenditure), sum(revenue)]
  const funds = [...new Set([...e.keys(), ...r.keys()])].sort()
  const bad = funds.filter((f) => (e.get(f) ?? 0) !== (r.get(f) ?? 0))
  return {
    name: '歳出と歳入の交差検算（会計ごと）',
    ok: bad.length === 0,
    detail:
      bad.length === 0
        ? `${funds.length} 会計すべてで一致。⚠️ 三鷹市の令和6年度当初予算について確認済みの条件付き検算であり、決算・企業会計・補正差分では成立しない`
        : bad.map((f) => `${f}: 歳出 ${yen(e.get(f) ?? 0)} ≠ 歳入 ${yen(r.get(f) ?? 0)}`).join(' / '),
  }
}

/**
 * 公表資料との突合。原典を再集計した値ではなく、外部の固定した資料と比べる。
 *
 * 合計だけでなく**款別まで全件**比べる。合計だけだと、款をまたぐ取り違えが相殺されて素通りする。
 */
export function publishedReconciliation(expenditure: CanonicalTable, revenue: CanonicalTable): Check[] {
  const P = MITAKA_2024_PUBLISHED
  const byKan = (t: CanonicalTable) => {
    const m = new Map<string, number>()
    for (const r of t.rows) if (r.fund_source === P.fund) m.set(String(r.kan_label), (m.get(String(r.kan_label)) ?? 0) + Number(r.source_amount))
    return m
  }
  const out: Check[] = []

  for (const [label, table, table_] of [
    ['歳出', expenditure, P.expenditureByKan],
    ['歳入', revenue, P.revenueByKan],
  ] as const) {
    const actual = byKan(table)
    const expected = table_.values
    const diffs: string[] = []
    for (const [kan, want] of Object.entries(expected)) {
      const got = actual.get(kan)
      if (got !== want) diffs.push(`${kan}: 変換後 ${got === undefined ? '無し' : yen(got)} ≠ 公表 ${yen(want)}`)
    }
    for (const kan of actual.keys()) if (!(kan in expected)) diffs.push(`${kan}: 公表資料に対応する款が無い`)

    out.push({
      name: `公表資料との突合（${P.title} ${table_.location}・${label}の款別）`,
      ok: diffs.length === 0,
      detail:
        diffs.length === 0
          ? `${Object.keys(expected).length} 款すべてが一致（${P.unit}単位。資料 SHA-256 ${P.sha256.slice(0, 12)}…）`
          : diffs.slice(0, 8).join(' / '),
    })

    // 公表値そのものの内部整合。転記ミスがあればここで落ちる
    const publishedSum = Object.values(expected).reduce((a, b) => a + b, 0)
    out.push({
      name: `公表値の内部整合（${label}の款別の和 = 公表の合計）`,
      ok: publishedSum === P.total,
      detail: `${yen(publishedSum)} / ${yen(P.total)} ${P.unit}`,
    })

    const converted = [...actual.values()].reduce((a, b) => a + b, 0)
    out.push({
      name: `公表資料との突合（一般会計 ${label}合計）`,
      ok: converted === P.total,
      detail: `変換後 ${yen(converted)} ${P.unit} / 公表 ${yen(P.total)} ${P.unit}（${P.documentUrl}）`,
    })
  }
  return out
}

/** COFOG の2つの保存則。**年度・会計・予算段階・direction ごとに見る**（全体合計だけだと会計間で相殺される） */
function cofogPreservation(canonical: CanonicalTable, derived: DerivedTable): Check[] {
  const groupKey = (r: Row) => [r.fiscal_year, r.fund_source, r.phase_id, r.direction].join(SEP)
  const before = new Map<string, number>()
  for (const r of canonical.rows) before.set(groupKey(r), (before.get(groupKey(r)) ?? 0) + Number(r.value))

  // 適格母集団は「対象外を除いた合計」。その内訳が割当済みと分類不能に尽きることを、
  // 別々に足し上げてから突き合わせる（同じ足し方で2回数えても検算にならない）
  const after = new Map<string, number>()
  const eligible = new Map<string, number>()
  const assignedPlusUnclassifiable = new Map<string, number>()
  const add = (m: Map<string, number>, k: string, v: number) => m.set(k, (m.get(k) ?? 0) + v)
  for (const r of derived.rows) {
    const k = groupKey(r)
    const v = Number(r.value)
    add(after, k, v)
    if (r.cofog_status !== 'out-of-scope') add(eligible, k, v)
    if (r.cofog_status === 'assigned' || r.cofog_status === 'unclassifiable') add(assignedPlusUnclassifiable, k, v)
  }

  const mismatched = [...before].filter(([k, v]) => after.get(k) !== v)
  const checks: Check[] = [
    {
      name: 'COFOG：原典の保存（全状態の合計 = 原典の合計）',
      ok: mismatched.length === 0,
      detail: mismatched.length === 0 ? `${before.size} 組（年度 × 会計 × 予算段階 × direction）すべてで一致` : mismatched.map(([k, v]) => `${k.replace(new RegExp(SEP, "g"), '/')}: ${yen(v)} ≠ ${yen(after.get(k) ?? 0)}`).join(' / '),
    },
    {
      name: 'COFOG：適格母集団の保存（割当済み + 分類不能 = 対象外を除いた合計）',
      ok: [...eligible].every(([k, v]) => assignedPlusUnclassifiable.get(k) === v),
      detail: `${eligible.size} 組で一致。適格母集団 ${yen([...eligible.values()].reduce((a, b) => a + b, 0))} 円`,
    },
  ]

  const multi = derived.rows.filter((r) => String(r.cofog_division_code).includes(';'))
  checks.push({ name: 'COFOG：1行あたりのディビジョンが1件以下', ok: multi.length === 0, detail: multi.length === 0 ? `${derived.rows.length} 行すべてで1件以下` : `${multi.length} 行が複数持つ` })

  const leaked = derived.rows.filter((r) => r.cofog_status !== 'assigned' && r.cofog_division_code !== '')
  checks.push({ name: 'COFOG：分類不能と対象外ではコードが空', ok: leaked.length === 0, detail: leaked.length === 0 ? '空であることを確認' : `${leaked.length} 行がコードを持つ` })

  const missingCounterpart = derived.rows.filter((r) => r.cofog_consolidation === 'eliminated' && (r.cofog_counterpart_ids === '' || r.cofog_consolidation_scope === ''))
  checks.push({ name: 'COFOG：消去する行に連結の範囲と相手側の識別子がある', ok: missingCounterpart.length === 0, detail: missingCounterpart.length === 0 ? `消去 ${derived.rows.filter((r) => r.cofog_consolidation === 'eliminated').length} 行すべてに記録あり` : `${missingCounterpart.length} 行で欠落` })

  const unbalanced = derived.consolidationPairs.filter((p) => p.eliminated !== p.counterpart)
  checks.push({
    name: 'COFOG：消去した金額が相手側と一致',
    ok: unbalanced.length === 0,
    detail:
      unbalanced.length === 0
        ? derived.consolidationPairs.map((p) => `${p.from}→${p.to} ${yen(p.eliminated)} 円`).join(' / ')
        : unbalanced.map((p) => `${p.from}→${p.to}: 消去 ${yen(p.eliminated)} ≠ 相手 ${yen(p.counterpart)}`).join(' / '),
  })
  return checks
}

/** 外部データと突合できる形か。接続キーが機械的に取り出せることを見る */
function joinability(expenditure: CanonicalTable, source: BudgetSource): Check {
  const bad = expenditure.rows.filter((r) => r.jurisdiction_code !== source.jurisdictionCode || !Number.isInteger(r.fiscal_year))
  return {
    name: '外部データとの接続キー（団体コード × 年度）',
    ok: bad.length === 0,
    detail: bad.length === 0 ? `全行が jurisdiction_code=${source.jurisdictionCode} と fiscal_year=${source.fiscalYear} を持つ` : `${bad.length} 行で欠落`,
  }
}

export function verifyAll(args: {
  source: BudgetSource
  expenditure: CanonicalTable
  revenue: CanonicalTable
  expenditureText: string
  revenueText: string
  derived: DerivedTable
  descriptor: Record<string, unknown>
}): Check[] {
  const { source, expenditure, revenue, derived, descriptor } = args
  return [
    multisetMatch(args.expenditureText, expenditure),
    multisetMatch(args.revenueText, revenue),
    cellRoundTrip(expenditure),
    cellRoundTrip(revenue),
    ...dependencies(expenditure),
    ...dependencies(revenue),
    idCollisions(expenditure),
    idCollisions(revenue),
    compositeKeyUnique(expenditure, '歳出'),
    compositeKeyUnique(revenue, '歳入'),
    amountConversion(expenditure, source),
    amountConversion(revenue, source),
    ...publishedReconciliation(expenditure, revenue),
    crossCheck(expenditure, revenue, source),
    ...cofogPreservation(expenditure, derived),
    joinability(expenditure, source),
    ...descriptorConformance(descriptor),
  ]
}
