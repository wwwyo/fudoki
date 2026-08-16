/**
 * # Fiscal Data Package 1.0.0 の descriptor と CSV を書く
 *
 * ⚠️ 参照するのは **1.0.0（`fiscal.datapackage.org`）だけ**。
 * `openspending/fiscal-data-package` の 0.3.0 と `specs.frictionlessdata.io` の 1.0-rc.1 は旧版で、
 * 0.3.0 にしかない `measures` / `dimensions` / `granularity` という語彙は使わない。
 *
 * 歳出と歳入は同じパッケージの別リソースにする。階層の意味が違うため、
 * 1つの表に混在させると互いに空の列が生じる。
 */
import { BUDGET_TAXONOMY_URL, CUSTOM_COLUMN_TYPES } from './columns'
import { COFOG_SOURCE, COFOG_VERSION } from './cofog'
import type { Provenance } from './extract'
import type { FieldSpec, Row } from './load'
import type { BudgetSource } from './source'

/** FDP の JSON Schema が `profile` にこの値を要求する（Tabular Data Package を継承しているため） */
const PROFILE = 'tabular-data-package'
const FDP_SPEC = { version: '1.0.0', url: 'https://fiscal.datapackage.org/', profile: 'https://fiscal.datapackage.org/profiles/fiscal-data-package.json' }

export type ResourceInput = {
  name: string
  title: string
  description: string
  fields: FieldSpec[]
  rows: Row[]
  provenance: Provenance | null
}

/** RFC 4180。原典に引用符は無いが、名称にカンマが現れる可能性はある */
function csvCell(v: string | number | undefined): string {
  const s = v === undefined ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(fields: FieldSpec[], rows: Row[]): string {
  const head = fields.map((f) => f.name).join(',')
  const body = rows.map((r) => fields.map((f) => csvCell(r[f.name])).join(','))
  return [head, ...body].join('\n') + '\n'
}

/**
 * `unique: true` の ColumnType を持つ列。FDP はこれらをまとめて複合主キーとみなす。
 *
 * Table Schema の `primaryKey` には**最小の実キーである `budget_line_id` だけ**を置く。
 * 複合キーの側は列数が多く（通貨のような定数列まで入る）主キーとしては冗長だが、
 * 「複合主キーが重複しないこと」は識別子の設計が依拠している前提そのものなので、
 * 別に書き出して検証の対象にする。
 */
export function fdpCompositeKey(fields: FieldSpec[], uniqueTypes: Set<string>): string[] {
  return fields.filter((f) => f.columnType && uniqueTypes.has(f.columnType)).map((f) => f.name)
}

export function buildDescriptor(
  source: BudgetSource,
  resources: ResourceInput[],
  uniqueTypes: Set<string>,
): Record<string, unknown> {
  return {
    profile: PROFILE,
    name: `jp-${source.jurisdictionCode}-budget-${source.fiscalYear}`,
    title: `${source.jurisdictionName} ${source.fiscalYearLabel}予算（${source.phase.label}）`,
    description:
      `${source.jurisdictionName}（全国地方公共団体コード ${source.jurisdictionCode}）の${source.fiscalYearLabel}${source.phase.label}を ` +
      `Fiscal Data Package ${FDP_SPEC.version} として構造化したもの。列の意味づけには Budget Standard Taxonomy の ColumnTypes を使う。` +
      (source.coverageNote ? `収録範囲は原典の注記に従い「${source.coverageNote}」。` : '') +
      `金額は原典の${source.amountUnit.label}を円へ正規化してある（原典の値と単位は別の列に残した）。`,
    version: '1.0.0',
    created: new Date().toISOString(),
    countryCode: 'JP',
    fiscalPeriod: { start: `${source.fiscalYear}-04-01`, end: `${source.fiscalYear + 1}-03-31` },
    licenses: [{ name: source.license.id, title: source.license.name, path: source.license.url }],
    /** CC BY が要求する帰属表示 */
    attribution: source.attribution,
    sources: [
      { title: source.attribution, path: source.landingPage },
      ...resources.flatMap((r) =>
        r.provenance
          ? [{ title: r.provenance.resourceName, path: r.provenance.requestUrl, sha256: r.provenance.sha256, fetchedAt: r.provenance.fetchedAt }]
          : [],
      ),
    ],
    /** 仕様の版と、依拠した taxonomy を明記する */
    fudoki: {
      specification: FDP_SPEC,
      standardTaxonomy: 'Budget Standard Taxonomy 1.0.0',
      cofog: { version: COFOG_VERSION, divisions: '01〜10', source: COFOG_SOURCE },
      note:
        '正本（expenditure / revenue）は原典を正規化しただけで fudoki の判断を含まない。' +
        'COFOG の割り当ては派生（expenditure-cofog）にある。FDP は全要素が任意なので、COFOG 列を持たない正本も適合した FDP になる。',
    },
    /**
     * 標準の taxonomy に加えて、fudoki が定義した ColumnType をインラインで載せる。
     * ⚠️ 標準側が正準と宣言する URL は 404 を返す（src/budget/taxonomy/budget-taxonomy.json 参照）。
     */
    columnTypes: [
      BUDGET_TAXONOMY_URL,
      CUSTOM_COLUMN_TYPES.map(({ why, ...def }) => ({ ...def, description: why })),
    ],
    resources: resources.map((r) => ({
      name: r.name,
      path: `${r.name}.csv`,
      profile: 'tabular-data-resource',
      title: r.title,
      description: r.description,
      format: 'csv',
      mediatype: 'text/csv',
      encoding: 'utf-8',
      dialect: { delimiter: ',', lineTerminator: '\n', header: true },
      ...(r.provenance
        ? { fudokiSource: { url: r.provenance.requestUrl, sha256: r.provenance.sha256, fetchedAt: r.provenance.fetchedAt, status: r.provenance.status, encoding: r.provenance.encoding, rows: r.provenance.rows } }
        : {}),
      schema: {
        fields: r.fields.map((f) => ({
          name: f.name,
          title: f.title,
          type: f.type,
          ...(f.description ? { description: f.description } : {}),
          ...(f.columnType ? { columnType: f.columnType } : {}),
          ...(f.labelOf ? { labelOf: f.labelOf } : {}),
        })),
        primaryKey: ['budget_line_id'],
        fdpCompositeKey: fdpCompositeKey(r.fields, uniqueTypes),
      },
    })),
  }
}
