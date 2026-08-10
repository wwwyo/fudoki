/**
 * manifest から web/survey.html 用の `web/_data.js` を生成する。
 * 手で書かない（manifest が SSOT で、ビューアはその射影）。
 *
 *   bun run scripts/build-viewer-data.ts
 */
import { Manifest } from '../src/extract/sources/schema'

const MANIFEST = new URL('../src/extract/sources/manifest.json', import.meta.url).pathname
const OUT = new URL('../web/_data.js', import.meta.url).pathname

const m = Manifest.parse(JSON.parse(await Bun.file(MANIFEST).text()))

type Dataset = { title: string; formats: string[]; license: string | null; url: string | null; count: number }
const ds = (d: Dataset | null | undefined) =>
  d ? { title: d.title, fmt: d.formats.join('/'), license: d.license, url: d.url, n: d.count } : null

const rows = Object.entries(m.jurisdictions).map(([code, j]) => {
  const t = j.transcript
  const o = j.openData
  const g = o.gikaiDayori
  return {
    code,
    name: j.name,
    fam: t.systemFamily,
    url: t.transcriptUrl,
    tenant: t.tenant ?? null,
    tenantId: t.tenantId ?? null,
    verdict: t.robots.verdict,
    ai: t.robots.aiCrawler,
    obs: t.robots.observation,
    cmt: t.hasCommittee,
    rec: t.recordType,
    fetch: t.gate.fetch,
    redist: t.gate.redistribute,
    constraints: t.gate.constraints,
    gateNote: t.gate.note ?? null,
    conf: t.confidence,
    notes: t.notes ?? null,
    ev: t.evidenceUrls ?? [],
    dsCount: o.tokyoCatalogDatasets ?? null,
    budget: ds(o.budget),
    roster: ds(o.memberRoster),
    proc: ds(o.procurement),
    dayori: g
      ? {
          ...ds(g)!,
          std: g.schemaCheck?.standard ?? null,
          scConf: g.schemaCheck?.conformance ?? null,
          extra: g.schemaCheck?.extraColumns ?? null,
          scNote: g.schemaCheck?.note ?? null,
        }
      : null,
    portal: o.ownPortal ?? null,
  }
})

const js =
  `window.DATA=${JSON.stringify(rows)};\n` +
  `window.META=${JSON.stringify({ generatedAt: m.generatedAt, policy: m.policy, note: m.note })};\n`
await Bun.write(OUT, js)
console.log(`${OUT} を生成した（${rows.length} 団体）`)
