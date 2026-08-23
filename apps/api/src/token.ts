/**
 * 不透明な pageToken。中身の形式は契約ではない（変えるときは v を上げる）。
 * offset は**フィルタ適用前の**chunk 内の行位置を指す。
 */

export type PageToken = {
  v: 1
  /** 発行時の配布物 revision。食い違ったら 410 */
  rev: string
  /** パーティション系列（例: cofog/09/all, lines/132195/2023-expenditure） */
  family: string
  /** 系列内の chunk 番号（chunk の無い系列は 0 固定） */
  chunk: number
  /** chunk 内の走査開始位置（フィルタ適用前） */
  off: number
  /** 正規化したフィルタの指紋。別条件のトークン流用を検出する */
  fh: string
}

export function encodePageToken(token: PageToken): string {
  const json = JSON.stringify(token)
  return btoa(json).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

export function decodePageToken(raw: string): PageToken | null {
  try {
    const b64 = raw.replaceAll('-', '+').replaceAll('_', '/')
    const parsed: unknown = JSON.parse(atob(b64))
    if (typeof parsed !== 'object' || parsed === null) return null
    const t = parsed as Record<string, unknown>
    if (
      t['v'] !== 1 ||
      typeof t['rev'] !== 'string' ||
      typeof t['family'] !== 'string' ||
      typeof t['chunk'] !== 'number' ||
      typeof t['off'] !== 'number' ||
      typeof t['fh'] !== 'string'
    ) {
      return null
    }
    return t as PageToken
  } catch {
    return null
  }
}
