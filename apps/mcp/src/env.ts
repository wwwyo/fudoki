/**
 * stdio 版の Env（apps/api/src/assets.ts の `Env`）の組み立て。
 *
 * Workers 版は `ASSETS` を binding（fetch 可能なオブジェクト）として渡されるが、
 * stdio プロセスにその binding は無い。procedure が読むのは
 * `apps/api/dist/assets/` 配下の JSON だけ（apps/api/src/procedure/*.ts が
 * すべて `readJsonAsset` 経由で読んでいる）なので、ここではそのディレクトリを
 * ファイルシステムから読んで同じ `fetch(input) => Promise<Response>` の形にする。
 *
 * `API_KEYS` と rate limiter は Hono の access-control middleware だけが使い、
 * procedure（= このプロセスが呼ぶ範囲）は一切参照しない。型を満たすためだけに
 * 「呼ばれたら壊れる」スタブを置く（黙って空を返すとバグを隠す）。
 */
import { readFile } from 'node:fs/promises'
import { join, resolve, sep } from 'node:path'
import type { Env } from '../../api/src/assets'

const DIST_ASSETS_DIR = resolve(import.meta.dir, '../../api/dist/assets')

/** dist/assets が無いまま起動されたときに、何をすれば直るかまで出して止める */
export async function assertAssetsBuilt(): Promise<void> {
  const marker = join(DIST_ASSETS_DIR, 'meta/jurisdictions.json')
  const found = await readFile(marker).then(
    () => true,
    () => false,
  )
  if (found) return
  console.error(
    [
      `apps/api の配布物（${DIST_ASSETS_DIR}）が見つからない。`,
      'apps/mcp は apps/api の procedure をそのまま呼ぶだけで、独自にデータを持たない。',
      '先に apps/api をビルドしてから起動すること:',
      '',
      '  bun run --cwd apps/api build.ts --allow-dirty',
      '',
    ].join('\n'),
  )
  process.exit(1)
}

/**
 * `ASSETS.fetch` の stdio 実装。渡ってくる input は procedure 側（readAsset）が
 * `new URL(path, 'https://assets.internal/').toString()` で組んだ文字列のみだが、
 * `Env['ASSETS']` の型は Request | URL | string を許すので、その3種を等しく扱う。
 */
function createFsAssets(rootDir: string): Env['ASSETS'] {
  return {
    async fetch(input) {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url)
      const relPath = decodeURIComponent(url.pathname).replace(/^\/+/, '')
      const filePath = resolve(rootDir, relPath)
      // rootDir の外に出ないことの検査（実際に来るのは paths.ts が組んだ相対パスだけだが、
      // 呼び出し側の実装ミスで `..` が混入したときに他ディレクトリを読まないための保険）
      if (filePath !== rootDir && !filePath.startsWith(rootDir + sep)) {
        return new Response(null, { status: 404 })
      }
      try {
        const body = await readFile(filePath)
        return new Response(new Uint8Array(body), { status: 200, headers: { 'content-type': 'application/json' } })
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code === 'ENOENT') return new Response(null, { status: 404 })
        throw e
      }
    },
  }
}

function unusedKVNamespace(bindingName: string): Env['API_KEYS'] {
  const reason = `${bindingName} は Hono の access-control middleware だけが使う。MCP サーバはその層を経由しないので呼ばれてはならない`
  return {
    get() {
      throw new Error(reason)
    },
    put() {
      throw new Error(reason)
    },
  }
}

function unusedRateLimiter(bindingName: string): Env['RATE_LIMIT_ANONYMOUS'] {
  const reason = `${bindingName} は Hono の access-control middleware だけが使う。MCP サーバはその層を経由しないので呼ばれてはならない`
  return {
    limit() {
      throw new Error(reason)
    },
  }
}

export function createEnv(): Env {
  return {
    ASSETS: createFsAssets(DIST_ASSETS_DIR),
    API_KEYS: unusedKVNamespace('API_KEYS'),
    RATE_LIMIT_ANONYMOUS: unusedRateLimiter('RATE_LIMIT_ANONYMOUS'),
    RATE_LIMIT_AUTHENTICATED: unusedRateLimiter('RATE_LIMIT_AUTHENTICATED'),
  }
}
