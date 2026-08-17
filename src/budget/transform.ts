/**
 * # Transform：正本へ COFOG を割り当てて派生を作る
 *
 * 正本はそのまま残し、派生を別リソースとして出す。
 * FDP は全要素が任意なので、**COFOG 列を持たない正本も適合した FDP になる**。
 * 両者を同じデータに混ぜると、市が公表した事実と fudoki の判断を利用者が区別できなくなる。
 */
import { assign, CONSOLIDATION_SCOPE, COFOG_DIVISIONS, type Assignment } from './cofog'
import type { CanonicalTable, FieldSpec, Row } from './load'

export type DerivedTable = {
  fields: FieldSpec[]
  rows: Row[]
  /** 消去した行と相手側の突合。連結が閉じているかを検算する */
  consolidationPairs: { from: string; to: string; eliminated: number; counterpart: number; counterpartIds: string[] }[]
}

const COFOG_FIELDS: FieldSpec[] = [
  { name: 'cofog_division_code', title: 'COFOG ディビジョンのコード', type: 'string', columnType: 'functional-classification:cofog:division:code', description: '分類不能と対象外の行では空' },
  { name: 'cofog_division_label', title: 'COFOG ディビジョン名', type: 'string', columnType: 'functional-classification:cofog:division:label', labelOf: 'functional-classification:cofog:division:code' },
  { name: 'cofog_status', title: '分類の軸', type: 'string', columnType: 'fudoki:cofog:status', description: 'assigned / unclassifiable / out-of-scope' },
  { name: 'cofog_consolidation', title: '連結の軸', type: 'string', columnType: 'fudoki:cofog:consolidation', description: 'retained / eliminated' },
  { name: 'cofog_consolidation_scope', title: '連結の範囲', type: 'string', columnType: 'fudoki:cofog:consolidation', description: '消去する行にのみ入る' },
  {
    name: 'cofog_counterpart_ids',
    title: '相手側の行の識別子',
    type: 'string',
    columnType: 'fudoki:cofog:counterpart-id',
    description:
      '消去する行の相手側（受け皿となる会計の他会計繰入金）の budget_line_id を `;` 区切りで並べたもの。' +
      '注意: 行と行の対応は1対1ではない（歳出の細々節と歳入の細々節が同じ切り方をしていない）。' +
      '金額が厳密に一致するのは会計の対どうしの合計であり、その突合結果はパイプライン報告にある',
  },
  { name: 'cofog_decided_at_level', title: '割り当てが決まった単位', type: 'string', columnType: 'fudoki:cofog:decided-at-level' },
  { name: 'cofog_basis', title: '割り当ての根拠', type: 'string', columnType: 'fudoki:cofog:basis' },
  { name: 'cofog_rule_id', title: '適用した規則', type: 'string', columnType: 'fudoki:cofog:basis' },
]

/** 受け皿の会計における相手側の歳入行。基金繰入金は会計間の移転ではないので外す */
function counterpartRows(revenue: CanonicalTable, fundLabel: string): Row[] {
  return revenue.rows.filter((r) => r.fund_label === fundLabel && String(r.kan_label).includes('繰入金') && !String(r.kou_label).includes('基金繰入金'))
}

export function transform(jurisdictionCode: string, expenditure: CanonicalTable, revenue: CanonicalTable): DerivedTable {
  const counterpartCache = new Map<string, Row[]>()
  const getCounterpart = (fund: string) => {
    let hit = counterpartCache.get(fund)
    if (!hit) counterpartCache.set(fund, (hit = counterpartRows(revenue, fund)))
    return hit
  }

  const pairTotals = new Map<string, { from: string; to: string; eliminated: number }>()
  const rows: Row[] = expenditure.rows.map((r) => {
    const a: Assignment & { ruleId: string } = assign(jurisdictionCode, {
      fund: String(r.fund_label),
      kan: String(r.kan_label),
      kou: String(r.kou_label),
      moku: String(r.moku_label),
      setsu: String(r.setsu_label),
    })

    let counterpartIds = ''
    if (a.consolidation === 'eliminated' && a.counterpartFund) {
      counterpartIds = getCounterpart(a.counterpartFund)
        .map((c) => String(c.budget_line_id))
        .join(';')
      const key = `${r.fund_label}→${a.counterpartFund}`
      const acc = pairTotals.get(key) ?? { from: String(r.fund_label), to: a.counterpartFund, eliminated: 0 }
      acc.eliminated += Number(r.value)
      pairTotals.set(key, acc)
    }

    return {
      ...r,
      cofog_division_code: a.division,
      cofog_division_label: a.division ? (COFOG_DIVISIONS[a.division] ?? '') : '',
      cofog_status: a.status,
      cofog_consolidation: a.consolidation,
      cofog_consolidation_scope: a.consolidation === 'eliminated' ? CONSOLIDATION_SCOPE : '',
      cofog_counterpart_ids: counterpartIds,
      cofog_decided_at_level: a.decidedAtLevel,
      cofog_basis: a.basis,
      cofog_rule_id: a.ruleId,
    }
  })

  const consolidationPairs = [...pairTotals.values()].map((p) => {
    const cp = getCounterpart(p.to)
    return { ...p, counterpart: cp.reduce((s, c) => s + Number(c.value), 0), counterpartIds: cp.map((c) => String(c.budget_line_id)) }
  })

  return { fields: [...expenditure.fields, ...COFOG_FIELDS], rows, consolidationPairs }
}
