/**
 * manifest に載っている取得先ホストの robots.txt を実際に取得し、
 * **原文そのまま**を証跡として保存する。
 *
 * 要約を持つと RFC 9309 準拠の再判定ができなくなるため、raw は加工しない。
 * 説明用の要約が要るなら別フィールドに置く。
 *
 *   bun run scripts/fetch-robots.ts            # 取得して差分を表示
 *   bun run scripts/fetch-robots.ts --write    # data/observations/robots.json へ保存
 */
import { Manifest } from './lib/gates'
import { UA } from './lib/source'

const MANIFEST = new URL('../ingestion/transcript-gates.json', import.meta.url).pathname
const OUT = new URL('../data/observations/robots.json', import.meta.url).pathname
const write = process.argv.includes('--write')

const m = Manifest.parse(JSON.parse(await Bun.file(MANIFEST).text()))

/** 取得先ホストごとに1回だけ引く（DB-Search の dbsr.jp のように同一テンプレートが多数ある） */
const hosts = new Map<string, string[]>()
for (const [code, j] of Object.entries(m.jurisdictions)) {
  const u = j.transcript.transcriptUrl
  if (!u) continue
  const h = new URL(u).origin
  hosts.set(h, [...(hosts.get(h) ?? []), code])
}

type Observation = {
  origin: string
  jurisdictions: string[]
  requestUrl: string
  status: number | null
  finalUrl: string | null
  contentType: string | null
  /** robots.txt の原文。加工しない。null は取得できなかったことを表す */
  raw: string | null
  sha256: string | null
  bytes: number | null
  fetchedAt: string
  userAgent: string
  error?: string
}

const results: Observation[] = []
for (const [origin, codes] of [...hosts].sort()) {
  const requestUrl = `${origin}/robots.txt`
  const base: Observation = {
    origin,
    jurisdictions: codes.sort(),
    requestUrl,
    status: null,
    finalUrl: null,
    contentType: null,
    raw: null,
    sha256: null,
    bytes: null,
    fetchedAt: new Date().toISOString(),
    userAgent: UA,
  }
  try {
    const res = await fetch(requestUrl, {
      headers: { 'User-Agent': UA },
      redirect: 'follow',
      signal: AbortSignal.timeout(20_000),
    })
    const buf = new Uint8Array(await res.arrayBuffer())
    const text = new TextDecoder('utf-8', { fatal: false }).decode(buf)
    const ct = res.headers.get('content-type')
    // robots.txt を要求して HTML が返るのは「robots.txt が無い」と同義に扱う
    const isHtml = /^\s*<(!DOCTYPE|html)/i.test(text) || (ct ?? '').includes('text/html')
    Object.assign(base, {
      status: res.status,
      finalUrl: res.url,
      contentType: ct,
      raw: res.ok && !isHtml ? text : null,
      bytes: buf.byteLength,
      sha256:
        res.ok && !isHtml
          ? new Bun.CryptoHasher('sha256').update(buf).digest('hex')
          : null,
    })
    if (res.ok && isHtml) base.error = 'robots.txt を要求したが HTML が返った（実質存在しない）'
  } catch (e) {
    base.error = e instanceof Error ? e.message : String(e)
  }
  const mark = base.raw ? '○' : base.status === 404 ? '·' : '✗'
  console.log(
    `  ${mark} ${origin.padEnd(46)} ${String(base.status ?? '—').padStart(3)} ` +
      `${base.raw ? `${base.bytes}B  ${base.sha256?.slice(0, 12)}` : (base.error ?? 'robots なし')}`,
  )
  results.push(base)
}

const withRobots = results.filter((r) => r.raw).length
console.log(`\nホスト ${results.length} / robots.txt あり ${withRobots} / 無し ${results.length - withRobots}`)

if (write) {
  await Bun.write(
    OUT,
    JSON.stringify(
      {
        note: 'robots.txt の原文証跡。要約は持たない。判定は policy 側で行い、ここは観測結果のみを保存する。',
        userAgent: UA,
        observations: results,
      },
      null,
      2,
    ) + '\n',
  )
  console.log(`${OUT} へ保存した`)
}
