/**
 * Budget Standard Taxonomy の ColumnType 一覧を、仕様の原文から取り出して取り込む。
 *
 * ⚠️ **仕様が「正準の場所」と宣言している URL は 404 を返す**（2026-08-16 実測）。
 *
 *   https://specs.frictionlessdata.io/taxonomies/fiscal/budgets.json → 404
 *
 * つまり ColumnType の一覧を機械可読な形で参照する経路が存在しない。
 * FDP は 2024-03 を最後に更新が止まっており、これは「採用した範囲は自分たちで保守する」
 * という前提が実際に必要になった1件目にあたる。
 *
 * そこで**仕様の原文（Markdown）を唯一の出所として一覧を起こし、リポジトリへ取り込む**。
 * 検証をネットワークに依存させないためでもある。
 *
 *   bun run scripts/fetch-fdp-taxonomy.ts
 */
import { UA, sha256 } from './lib/source'

const SPEC_URL = 'https://raw.githubusercontent.com/frictionlessdata/datapackage-fiscal/main/content/docs/specifications/fiscal-data-package-budgets.md'
const OUT = new URL('../fdp/budget-taxonomy.json', import.meta.url).pathname
/** 仕様が正準と宣言しているが 404 を返す URL。事実として残す */
const DECLARED_CANONICAL = 'https://specs.frictionlessdata.io/taxonomies/fiscal/budgets.json'

export type ColumnTypeDef = { name: string; dataType: string; unique?: boolean; labelOf?: string; prior?: string }

/** `level{1..8}` のような範囲表記を実際の名前へ展開する */
function expand(name: string): string[] {
  const m = /\{(\d+)\.\.(\d+)\}/.exec(name)
  if (!m) return [name]
  const [from, to] = [Number(m[1]), Number(m[2])]
  return Array.from({ length: to - from + 1 }, (_, i) => name.replace(m[0], String(from + i)))
}

export function parseTaxonomy(markdown: string): ColumnTypeDef[] {
  const out: ColumnTypeDef[] = []
  // `##### \`name\`` から次の見出しまでを1つの定義として読む
  const blocks = markdown.split(/^#####\s+/m).slice(1)
  for (const block of blocks) {
    const head = /^`([^`]+)`/.exec(block)
    if (!head) continue
    const body = block.split(/^#/m)[0]!
    const prop = (key: string) => new RegExp(`^-\\s+_${key}_:\\s*\`?([^\`\\n]+)\`?\\s*$`, 'm').exec(body)?.[1]?.trim()
    const dataType = prop('dataType')
    if (!dataType) continue
    const unique = prop('unique')?.toLowerCase() === 'true'
    const labelOf = prop('labelOf')
    const prior = prop('prior')

    for (const name of expand(head[1]!)) {
      // labelOf / prior 側も同じ範囲表記を持つので、レベル番号を合わせる
      const level = /:level(\d+):/.exec(name)?.[1]
      const align = (v: string | undefined) => (v && level ? v.replace(/:level\d+:/, `:level${level}:`) : v)
      out.push({
        name,
        dataType,
        ...(unique ? { unique } : {}),
        ...(labelOf ? { labelOf: align(labelOf)! } : {}),
        ...(prior ? { prior: align(prior)! } : {}),
      })
    }
  }
  return out
}

const res = await fetch(SPEC_URL, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30_000) })
if (!res.ok) throw new Error(`仕様を取得できない: ${res.status} ${SPEC_URL}`)
const bytes = new Uint8Array(await res.arrayBuffer())
const markdown = new TextDecoder().decode(bytes)
const columnTypes = parseTaxonomy(markdown)

const canonical = await fetch(DECLARED_CANONICAL, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30_000) }).catch(() => null)

await Bun.write(
  OUT,
  JSON.stringify(
    {
      note: '仕様の原文から起こした Budget Standard Taxonomy の ColumnType 一覧。仕様が正準と宣言する URL が 404 を返すため、fudoki 側で保守する。',
      specVersion: '1.0.0',
      declaredCanonicalUrl: DECLARED_CANONICAL,
      declaredCanonicalStatus: canonical?.status ?? null,
      source: { url: SPEC_URL, sha256: sha256(bytes), fetchedAt: new Date().toISOString() },
      generatedBy: 'scripts/fetch-fdp-taxonomy.ts',
      count: columnTypes.length,
      columnTypes,
    },
    null,
    2,
  ) + '\n',
)

console.log(`✓ ${columnTypes.length} 件の ColumnType を ${OUT} へ書き出した`)
console.log(`  仕様が正準と宣言する ${DECLARED_CANONICAL} は ${canonical?.status ?? '取得不可'}`)
