import { expect, test } from 'bun:test'
import { decodePageToken, encodePageToken } from '../src/token'

test('pageToken roundtrip', () => {
  const token = { v: 1 as const, rev: 'abc', family: 'cofog/09/all', chunk: 2, off: 500, fh: 'deadbeef' }
  expect(decodePageToken(encodePageToken(token))).toEqual(token)
})

test('malformed tokens decode to null', () => {
  expect(decodePageToken('not-a-token')).toBeNull()
  expect(decodePageToken(btoa('{"v":2}'))).toBeNull()
  expect(decodePageToken(btoa('[]'))).toBeNull()
  expect(decodePageToken('')).toBeNull()
})
