/**
 * # Load：原典1行を正本1行へ写す
 *
 * ここまでは**原典に無い情報を足さない**。出力（正本）は原文と突き合わせて検証できる。
 * 判断が入るのは Transform（COFOG の割り当て）から。
 *
 * この段でやるのは、コードと名称の分離、年度の付与、円への正規化、識別子の付与、
 * ColumnType の割り当ての5つ。階層は潰さず列として保持する（パーサ設計の原則2）。
 */
import { AMOUNT_COLUMN, absentLevelMarkers, levelsFor, type LevelSpec } from './columns'
import type { Provenance } from './extract'
import { splitRows } from './extract'
import type { BudgetSource, Direction } from './source'

/** 出力の1列。datapackage.json の field 定義と CSV のヘッダの両方の出所になる */
export type FieldSpec = {
  name: string
  title: string
  type: 'string' | 'integer' | 'number'
  columnType?: string
  labelOf?: string
  description?: string
}

export type Row = Record<string, string | number>

export type CanonicalTable = {
  direction: Direction
  slug: string
  fields: FieldSpec[]
  rows: Row[]
  levels: LevelSpec[]
  provenance: Provenance
  /** 「その階層が無い」と宣言済みのセル。想定内なので件数だけ数える */
  absentLevelCells: number
  /** `NN名称` でも宣言済みのプレースホルダでもないセル。0 でなければ報告に出す */
  irregularCells: { row: number; column: string; cell: string }[]
}

/** 原典のセル。`01議会費` を code=`01` / label=`議会費` に割る */
export type Cell = { code: string; label: string; source: string }

/**
 * セルを分解する。
 *
 * コードの桁数は階層ごとの宣言（`LevelSpec.codeDigits`）から受け取る。決め打ちにしない。
 * 三鷹市は2桁のコードに名称を直付けする。歳入の細々節だけは階層が無いことを `0` で表すため、
 * `NN名称` に当たらないセルは**コードとして丸ごと残し、名称を空にする**。
 * こうすると `code + label` が必ず原文に戻り、検証がそのまま効く。
 */
export function splitCell(source: string, codeDigits: number): Cell {
  const m = new RegExp(`^(\\d{${codeDigits}})(.+)$`).exec(source)
  return m ? { code: m[1]!, label: m[2]!, source } : { code: source, label: '', source }
}

/** 原典に引用符が現れたら、素朴な分割では壊れるので検出して落とす */
function assertNoQuotes(header: string[], rows: string[][]): void {
  const bad = [...header, ...rows.flat()].find((c) => c.includes('"'))
  if (bad !== undefined) throw new Error(`原典に引用符が現れた（${bad}）。単純なカンマ分割では壊れるので、パーサを直すまで正本を生成しない`)
}

/** 列名の連番プレフィックスを外す（`04目` → `目`） */
const stripIndex = (c: string) => c.replace(/^[0-9０-９]+[._\-\s]*/, '').trim()

/**
 * 宣言した階層が原典の列構成と一致するかを見る。
 *
 * ⚠️ 資料名ではなく実物の列で判定する（パーサ設計の原則3）。
 * ずれたまま通すと、列の意味を取り違えた正本が「検証を通った」状態で出る。
 */
function assertHeaderMatches(header: string[], levels: LevelSpec[], resourceName: string): void {
  const expected = [...levels.map((l) => l.sourceColumn), AMOUNT_COLUMN]
  const actual = header.map(stripIndex)
  if (expected.length !== actual.length || expected.some((e, i) => e !== actual[i])) {
    throw new Error(`原典の列構成が宣言と違う（${resourceName}）\n  宣言: ${expected.join(' / ')}\n  実物: ${actual.join(' / ')}`)
  }
}

/**
 * 行の識別子。**完全修飾パスから導き、衝突は救済しない。**
 *
 * 出現順の連番を採るとパーサを直すたびに全行の対応が崩れる（別 PJ の実測で、
 * パーサ修正をまたいで同じ対象を指し続けた割合は連番 6.6%、中身由来キー 約95%）。
 *
 * ⚠️ **コードだけのパスでは足りない。** 三鷹市の細々節は同じ親の下でコードを再利用しており、
 * 実測で 710 箇所・1,615 行がコードのパスでは衝突する（例: 節`08旅費` の下に
 * `01議員普通旅費` と `01議員管外旅費` が並ぶ）。名称まで含めたセル全文のパスなら
 * 5,613 行すべてが一意になるので、**パスの構成要素をセル全文に取る**。
 *
 * 可読性は `hierarchy_path` 列（コードの連結）が担い、識別子は衝突しないことを担う。
 */
export function budgetLineId(scope: { jurisdictionCode: string; fiscalYear: number; direction: Direction; phaseId: string }, cells: Cell[]): string {
  const qualified = [scope.jurisdictionCode, String(scope.fiscalYear), scope.direction, scope.phaseId, ...cells.map((c) => c.source)].join('')
  const digest = new Bun.CryptoHasher('sha256').update(qualified).digest('hex').slice(0, 16)
  return `${scope.jurisdictionCode}:${scope.fiscalYear}:${scope.direction}:${scope.phaseId}:${digest}`
}

function fieldsFor(source: BudgetSource, levels: LevelSpec[]): FieldSpec[] {
  const fields: FieldSpec[] = [
    { name: 'budget_line_id', title: '予算行の識別子', type: 'string', columnType: 'budget-line-id', description: '団体コード・年度・direction・予算段階と、階層のセル全文から導いた安定キー' },
    { name: 'jurisdiction_code', title: '全国地方公共団体コード', type: 'string', columnType: 'fudoki:jurisdiction:code' },
    { name: 'jurisdiction_label', title: '地方公共団体名', type: 'string', columnType: 'fudoki:jurisdiction:label', labelOf: 'fudoki:jurisdiction:code' },
    { name: 'fiscal_year', title: '会計年度（西暦）', type: 'integer', columnType: 'date:fiscal-year', description: '原典に年度の列が無いため、CKAN のリソース名から解決して付与した' },
    { name: 'direction', title: '支出と収入の別', type: 'string', columnType: 'direction' },
    { name: 'phase_id', title: '予算段階', type: 'string', columnType: 'phase:id' },
    { name: 'phase_label', title: '予算段階の表示名', type: 'string', columnType: 'phase:label', labelOf: 'phase:id' },
  ]
  for (const l of levels) {
    fields.push(
      { name: `${l.key}_code`, title: `${l.sourceColumn}コード`, type: 'string', columnType: l.codeType },
      { name: `${l.key}_label`, title: `${l.sourceColumn}名`, type: 'string', columnType: l.labelType, labelOf: l.codeType },
      { name: `${l.key}_source`, title: `${l.sourceColumn}（原典のセル）`, type: 'string', columnType: 'fudoki:source:cell' },
    )
  }
  fields.push(
    { name: 'hierarchy_path', title: '階層のコードパス', type: 'string', columnType: 'fudoki:hierarchy-path', description: '可読性のための列であって識別子ではない。三鷹市の歳出では細々節のコードが同じ節の下で再利用されるため（実測 710 箇所）、このパスが一意なのは節までで、細々節までは一意でない' },
    { name: 'value', title: `金額（${source.currency}）`, type: 'number', columnType: 'value', description: `原典の${source.amountUnit.label}を円へ正規化した値` },
    { name: 'currency', title: '通貨', type: 'string', columnType: 'value-currency:code' },
    { name: 'source_amount', title: '原典の金額', type: 'number', columnType: 'fudoki:source:amount' },
    { name: 'source_amount_unit', title: '原典の金額の単位', type: 'string', columnType: 'fudoki:source:amount-unit' },
    { name: 'source_row', title: '原典の物理行番号', type: 'integer', columnType: 'fudoki:source:row', description: 'ヘッダを1行目として数える。特定のスナップショット内でのみ意味を持つ' },
  )
  return fields
}

/** 整数として厳密に読む。桁あふれと非整数を通さない */
function parseAmount(raw: string, rowNumber: number): number {
  if (!/^-?\d+$/.test(raw)) throw new Error(`${rowNumber} 行目の金額「${raw}」が整数ではない`)
  const n = Number(raw)
  if (!Number.isSafeInteger(n)) throw new Error(`${rowNumber} 行目の金額「${raw}」が安全な整数の範囲を超える`)
  return n
}

export function load(source: BudgetSource, spec: BudgetSource['resources'][number], extracted: { text: string; provenance: Provenance }): CanonicalTable {
  const levels = levelsFor(source.jurisdictionCode, spec.direction)
  const all = splitRows(extracted.text)
  const header = all[0]!
  const body = all.slice(1)

  assertNoQuotes(header, body)
  assertHeaderMatches(header, levels, spec.resourceName)

  const absent = new Set(absentLevelMarkers(source.jurisdictionCode))
  const irregularCells: CanonicalTable['irregularCells'] = []
  let absentLevelCells = 0
  const rows: Row[] = []

  for (const [i, raw] of body.entries()) {
    const rowNumber = i + 2 // ヘッダが1行目
    if (raw.length !== levels.length + 1) throw new Error(`${rowNumber} 行目の列数が ${raw.length}（期待 ${levels.length + 1}）`)

    const cells = levels.map((l, j) => {
      const cell = splitCell(raw[j]!, l.codeDigits)
      if (cell.label === '') {
        if (absent.has(cell.source)) absentLevelCells++
        else irregularCells.push({ row: rowNumber, column: l.sourceColumn, cell: cell.source })
      }
      return cell
    })
    const amount = parseAmount(raw[levels.length]!, rowNumber)

    const row: Row = {
      budget_line_id: budgetLineId(
        { jurisdictionCode: source.jurisdictionCode, fiscalYear: source.fiscalYear, direction: spec.direction, phaseId: source.phase.id },
        cells,
      ),
      jurisdiction_code: source.jurisdictionCode,
      jurisdiction_label: source.jurisdictionName,
      fiscal_year: source.fiscalYear,
      direction: spec.direction,
      phase_id: source.phase.id,
      phase_label: source.phase.label,
    }
    for (const [j, l] of levels.entries()) {
      const c = cells[j]!
      row[`${l.key}_code`] = c.code
      row[`${l.key}_label`] = c.label
      row[`${l.key}_source`] = c.source
    }
    row.hierarchy_path = levels.map((l, j) => `${l.sourceColumn}${cells[j]!.code}`).join('/')
    row.value = amount * source.amountUnit.multiplier
    row.currency = source.currency
    row.source_amount = amount
    row.source_amount_unit = source.amountUnit.label
    row.source_row = rowNumber
    rows.push(row)
  }

  assertNoIdCollision(rows, spec.resourceName)

  return { direction: spec.direction, slug: spec.slug, fields: fieldsFor(source, levels), rows, levels, provenance: extracted.provenance, absentLevelCells, irregularCells }
}

/**
 * **衝突したら正本を生成しない。**
 *
 * 連番で救済すると、行の追加や並べ替えで採番が変わり、避けたはずの出現順の問題が
 * 重複グループの中で再発する。識別子を空にするのも駄目で、`budget-line-id` は
 * `unique: true`＝ FDP 上の複合主キーに入るため重複する。1行へ集約するのも、
 * 原典1行と変換後1行が対応するという前提を壊し、多重集合としての一致を検証できなくする。
 */
function assertNoIdCollision(rows: Row[], resourceName: string): void {
  const seen = new Map<string, number[]>()
  for (const r of rows) {
    const id = String(r.budget_line_id)
    const at = seen.get(id)
    if (at) at.push(Number(r.source_row))
    else seen.set(id, [Number(r.source_row)])
  }
  const collisions = [...seen].filter(([, at]) => at.length > 1)
  if (collisions.length === 0) return
  const detail = collisions.map(([id, at]) => `  ${id} ← 原典 ${at.join(', ')} 行目`).join('\n')
  throw new Error(
    `budget-line-id が ${collisions.length} 組衝突した（${resourceName}）。連番で救済せず生成を止める。\n` +
      `原典の性質か写像の設計かを判断し、階層の取り方を直すこと。\n${detail}`,
  )
}
