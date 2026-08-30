import { describe, expect, test } from 'bun:test'
import { classifyPath } from './path-class'

describe('classifyPath', () => {
  test('excludes docs UI, spec, and root/openapi.json redirects', () => {
    for (const p of ['/', '/openapi.json', '/v0', '/v0/', '/v0/openapi.json']) {
      expect(classifyPath(p)).toBe('excluded')
    }
  })

  test('classifies /rpc/* as rpc regardless of sub-path', () => {
    expect(classifyPath('/rpc')).toBe('rpc')
    expect(classifyPath('/rpc/listJurisdictions')).toBe('rpc')
  })

  test('classifies /v0/* query endpoints and passthrough as keyed', () => {
    expect(classifyPath('/v0/jurisdictions')).toBe('keyed')
    expect(classifyPath('/v0/budgets/-/statement')).toBe('keyed')
    expect(classifyPath('/v0/datapackages/132195/expenditure.csv')).toBe('keyed')
  })

  test('does not over-match: /v0openapi.json or /rpcfoo are not excluded/rpc', () => {
    expect(classifyPath('/v0openapi.json')).toBe('keyed')
    expect(classifyPath('/rpcfoo')).toBe('keyed')
  })
})
