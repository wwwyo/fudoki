import { afterAll, beforeAll, describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { PipelineOverview } from './overview'

const originalStorage = Object.getOwnPropertyDescriptor(
  globalThis,
  'localStorage'
)
const originalBase = process.env.BASE_URL

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null },
  })
  process.env.BASE_URL = '/'
})

afterAll(() => {
  if (originalStorage) {
    Object.defineProperty(globalThis, 'localStorage', originalStorage)
  } else {
    Reflect.deleteProperty(globalThis, 'localStorage')
  }
  if (originalBase === undefined) delete process.env.BASE_URL
  else process.env.BASE_URL = originalBase
})

describe('PipelineOverview', () => {
  test('報告が未生成でも概要・全体像・repo の案内を順に読める', () => {
    const markup = renderToStaticMarkup(
      <PipelineOverview data={null} error={null} />
    )
    const summary = markup.indexOf('id="summary"')
    const collection = markup.indexOf('id="collection"')
    const repository = markup.indexOf('id="repository"')

    expect(summary).toBeGreaterThan(-1)
    expect(collection).toBeGreaterThan(summary)
    expect(repository).toBeGreaterThan(collection)
    expect(markup).toContain('収録済みの自治体を読み込み中')
    expect(markup).toContain('pipeline/dbt/models/intermediate/fiscal/')
    expect(markup).toContain('pipeline/dbt/models/marts/fiscal/')
    expect(markup).not.toContain('ここで判断を加える')
  })

  test('読み込みが失敗しても共通案内を保持し、団体選択にエラーを表示する', () => {
    const markup = renderToStaticMarkup(
      <PipelineOverview data={null} error="pipeline.json がありません" />
    )

    expect(markup).toContain('id="summary"')
    expect(markup).toContain('id="collection"')
    expect(markup).toContain('id="repository"')
    expect(markup).toContain('自治体別の検証データを読み込めませんでした')
    expect(markup).toContain('pipeline.json がありません')
    expect(markup).not.toContain('収録済みの自治体を読み込み中')
  })
})
