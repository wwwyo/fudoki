import { z } from 'zod'
import { sha256Schema } from '@fudoki/data-contracts'
import { sha256Hex } from './apiKey'
import { versionRefSchema } from '../contract'

const payloadSchema = z
  .object({
    v: z.literal(2),
    versions: z.array(versionRefSchema).max(100),
    expiresAt: z.number().int(),
    fingerprint: sha256Schema,
    after: z.tuple([z.string(), z.string()]),
  })
  .strict()
export type Cursor = z.infer<typeof payloadSchema>
const encoder = new TextEncoder()
function base64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '')
}
function unbase64(value: string): Uint8Array<ArrayBuffer> {
  if (!/^[a-zA-Z0-9_-]+$/.test(value))
    throw new Error('Invalid cursor encoding')
  return Uint8Array.from(
    atob(value.replaceAll('-', '+').replaceAll('_', '/')),
    (c) => c.charCodeAt(0)
  )
}
async function key(secret: string) {
  if (!secret || secret.length < 32)
    throw new Error('CURSOR_SECRET must contain at least 32 characters')
  return crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify']
  )
}
export async function fingerprint(value: unknown): Promise<string> {
  return sha256Hex(JSON.stringify(value))
}
export async function encodeCursor(
  cursor: Cursor,
  secret: string
): Promise<string> {
  const body = base64(
    encoder.encode(JSON.stringify(payloadSchema.parse(cursor)))
  )
  return `${body}.${base64(new Uint8Array(await crypto.subtle.sign('HMAC', await key(secret), encoder.encode(body))))}`
}
export async function decodeCursor(
  value: string,
  secret: string
): Promise<Cursor> {
  if (value.length > 8192) throw new Error('Invalid cursor')
  const pieces = value.split('.')
  if (pieces.length !== 2) throw new Error('Invalid cursor')
  const [body, signature] = pieces as [string, string]
  const valid = await crypto.subtle.verify(
    'HMAC',
    await key(secret),
    unbase64(signature),
    encoder.encode(body)
  )
  if (!valid) throw new Error('Invalid cursor signature')
  const payload = payloadSchema.parse(
    JSON.parse(new TextDecoder().decode(unbase64(body)))
  )
  if (payload.expiresAt <= Date.now()) throw new Error('Cursor expired')
  return payload
}
