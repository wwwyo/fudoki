import {
  manifestSchema,
  releaseIdSchema,
  type R2Bucket,
  type ReleaseManifest,
} from '@fudoki/data-contracts'

export interface Env {
  RELEASES: R2Bucket
}
const immutable = 'public, max-age=31536000, immutable'
const MAX_MANIFEST_BYTES = 4 * 1024 * 1024
function reply(status: number, message: string) {
  return Response.json(
    { error: message },
    {
      status,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      },
    }
  )
}
async function readManifest(
  bucket: R2Bucket,
  releaseId: string
): Promise<{
  manifest: ReleaseManifest
  body: ArrayBuffer
  sha: string
} | null> {
  const object = await bucket.get(`releases/${releaseId}/manifest.json`)
  if (!object) return null
  if (object.size > MAX_MANIFEST_BYTES)
    throw new Error('Manifest exceeds the supported size')
  const body = await object.arrayBuffer()
  const manifest = manifestSchema.parse(
    JSON.parse(new TextDecoder().decode(body))
  )
  if (manifest.releaseId !== releaseId)
    throw new Error('Manifest release ID differs from its key')
  if (new Set(manifest.files.map((f) => f.path)).size !== manifest.files.length)
    throw new Error('Manifest contains duplicate file paths')
  const hash = await crypto.subtle.digest('SHA-256', body)
  return {
    manifest,
    body,
    sha: [...new Uint8Array(hash)]
      .map((n) => n.toString(16).padStart(2, '0'))
      .join(''),
  }
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== 'GET' && request.method !== 'HEAD')
      return reply(405, 'METHOD_NOT_ALLOWED')
    const path = new URL(request.url).pathname
    if (path === '/contract')
      return Response.json(
        { contractVersion: 1 },
        {
          headers: {
            'Cache-Control': 'no-store',
            'Access-Control-Allow-Origin': '*',
          },
        }
      )
    const match =
      /^\/releases\/(r-[a-f0-9]{32})\/(manifest\.json|catalog\.json|fiscal\/\d{6}\/[a-z_]+\.(?:csv|json))$/.exec(
        path
      )
    if (!match || !releaseIdSchema.safeParse(match[1]).success)
      return reply(404, 'NOT_FOUND')
    const releaseId = match[1]!,
      file = match[2]!
    try {
      const entry = await readManifest(env.RELEASES, releaseId)
      if (!entry) return reply(404, 'NOT_FOUND')
      const attributes =
        file === 'manifest.json'
          ? {
              sha256: entry.sha,
              bytes: entry.body.byteLength,
              contentType: 'application/json; charset=utf-8',
            }
          : entry.manifest.files.find((f) => f.path === file)
      if (!attributes) return reply(404, 'NOT_FOUND')
      const headers = new Headers({
        'Content-Type': attributes.contentType,
        'Content-Length': String(attributes.bytes),
        ETag: `"${attributes.sha256}"`,
        'X-Fudoki-Release': releaseId,
        'Cache-Control': immutable,
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': 'ETag,X-Fudoki-Release,Content-Length',
      })
      if (request.headers.get('if-none-match') === headers.get('ETag')) {
        headers.delete('Content-Length')
        return new Response(null, { status: 304, headers })
      }
      if (file === 'manifest.json')
        return new Response(request.method === 'HEAD' ? null : entry.body, {
          headers,
        })
      const key = `releases/${releaseId}/${file}`
      if (request.method === 'HEAD') {
        const object = await env.RELEASES.head(key)
        if (!object || object.size !== attributes.bytes)
          throw new Error('Published file is missing or differs in size')
        return new Response(null, { headers })
      }
      const object = await env.RELEASES.get(key)
      if (!object || object.size !== attributes.bytes)
        throw new Error('Published file is missing or differs in size')
      return new Response(object.body, { headers })
    } catch (error) {
      console.error(
        JSON.stringify({
          event: 'download_failed',
          releaseId,
          file,
          error: error instanceof Error ? error.message : String(error),
        })
      )
      return reply(503, 'RELEASE_UNAVAILABLE')
    }
  },
}
