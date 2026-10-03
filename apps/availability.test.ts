import { expect, test } from 'bun:test'
import api from './api/worker'
import web from './web/worker'
import docs from './docs/worker'

for (const [name, worker] of Object.entries({ api, web, docs })) {
  test(`${name} returns an uncached server error without service bindings`, async () => {
    const response = worker.fetch()
    expect(response.status).toBe(500)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(await response.text()).toBe('Temporarily unavailable\n')
  })
}
