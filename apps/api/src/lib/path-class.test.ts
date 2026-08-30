import { describe, expect, test } from 'bun:test'
import { ROOT_PATH, ROOT_SPEC_REDIRECT_PATH, V0_DOCS_PATH, V0_PREFIX, V0_SPEC_PATH } from '../spec'
import { classifyPath } from './path-class'

/**
 * 除外パスは spec.ts の定数から組み立てて期待値を作る（リテラルを手で
 * 二重に書かない）。この単体テストは classifyPath の分岐ロジック
 * （prefix マッチ・over-match しないこと・既定 keyed へのフォールバック）を
 * 検査するためのもので、「除外がリテラルの写しではなく実際の設定と
 * 連動しているか」は index.test.ts 側（limiter を必ず失敗させても
 * 除外パスは通ることを見るテスト）が担う。
 */
describe('classifyPath', () => {
  test('excludes docs UI, spec, and root/openapi.json redirects', () => {
    for (const p of [ROOT_PATH, ROOT_SPEC_REDIRECT_PATH, V0_PREFIX, `${V0_PREFIX}${V0_DOCS_PATH}`, `${V0_PREFIX}${V0_SPEC_PATH}`]) {
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
