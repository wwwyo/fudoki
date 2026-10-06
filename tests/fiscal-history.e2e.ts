import {
  beforeEach,
  afterEach,
  describe,
  test,
  type Browser,
} from '@e2e-dev/web'
import { expect } from 'e2e'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdirSync, writeFileSync } from 'node:fs'

const run = promisify(execFile)
const raw = 'source.fudoki.raw_132195_history.data'
const stage = 'model.fudoki.stg_132195__budget_history'
const history = 'model.fudoki.int_fiscal_budget_history'
const changes = 'model.fudoki.fiscal_expenditure_budget_changes'
const supplementary = 'model.fudoki.int_supplementary_expenditure_changes'
const issue3 =
  'e322f20a1bfc32099a3271dad9fa38d23c7c45d9f0ce1b7cc45eb8f258a6817f'
const initial =
  '21fc642dc4ca89acab6ea18632d6ee8539949272ecba65c78231a37a71ba6ee9'

async function rows(base: string, node: string) {
  const query = new URLSearchParams({
    node,
    code: '132195',
    year: '2023',
    dir: 'expenditure',
  })
  const response = await fetch(new URL(`/local/rows?${query}`, base))
  expect(response.status).toBe(200)
  const table = await response.json()
  expect(table.kind).toBe('table')
  expect(table.truncated).toBe(false)
  return table.rows.map((row: unknown[]) =>
    Object.fromEntries(
      table.columns.map((column: string, index: number) => [column, row[index]])
    )
  ) as Record<string, any>[]
}

function session(browser: Browser) {
  const evaluate = (expression: string) =>
    browser.evaluate<any>(`() => (${expression})`)
  async function settle(expression: string) {
    let result: any
    await expect
      .poll(
        async () => {
          result = await evaluate(expression)
          return Boolean(result)
        },
        { timeout: 20_000 }
      )
      .toBe(true)
    return result
  }
  async function edge(from: string, to: string) {
    // Preserve the old check's graph selection. Dense SVG hit paths overlap at fit zoom.
    await evaluate(
      `(()=>{const path=document.querySelector('[data-edge="${from}|${to}"]');if(!path)throw new Error('missing lineage edge');path.dispatchEvent(new MouseEvent('click',{bubbles:true}));return true})()`
    )
  }
  async function selectRow(side: number, suffix: string, position: number) {
    // Tables virtualize rows; scroll to materialize the target before tapping it.
    await evaluate(
      `(()=>{const box=document.querySelectorAll('.io .rows')[${side}];box.scrollTop=${position * 24};box.dispatchEvent(new Event('scroll'));return true})()`
    )
    await settle(
      `Boolean(document.querySelectorAll('.io .rows')[${side}]?.querySelector('tr[data-sr*="${suffix}"]'))`
    )
    const selector = await evaluate(
      `(()=>{const boxes=[...document.querySelectorAll('.io .rows')];const box=boxes[${side}];const all=[...document.querySelectorAll('.io .rows tr[data-sr*="${suffix}"]')];return all.findIndex(row=>box.contains(row))})()`
    )
    await browser
      .locator(`.io .rows tr[data-sr*="${suffix}"]`)
      .nth(selector)
      .tap()
  }
  const selection = () =>
    evaluate(
      `([...document.querySelectorAll('.io .rows tr.rowsel')].map(e=>({key:e.getAttribute('data-sr'),text:e.innerText})))`
    )
  return { evaluate, settle, edge, selectRow, selection }
}

beforeEach(async ({ app, browser }) => {
  await app.open('/pipeline/132195/?y=2023')
  await expect(browser.locator('[data-edge]').first()).toBeVisible({
    timeout: 20_000,
  })
})
afterEach(async ({ app }) => {
  await app.screenshot('fiscal-history')
})

describe('狛江市2023年度二目の補正予算', { tags: ['fiscal-history'] }, () => {
  test(
    'AC1: adopted inputs reach initial, changes and settlement-link marts',
    { timeout: 60_000, tags: ['history-ac1'] },
    async ({ app, browser }) => {
      const base = app.baseUrl!
      const rowsForNode = (node: string) => rows(base, node)

      const [money, budgetChanges, links, allInitialLines, items, references, details] =
        await Promise.all([
          rowsForNode(history),
          rowsForNode(changes),
          rowsForNode('model.fudoki.fiscal_expenditure_settlement_links'),
          rowsForNode('model.fudoki.fiscal_initial_expenditure_budget_lines'),
          rowsForNode('model.fudoki.fiscal_expenditure_budget_items'),
          rowsForNode('model.fudoki.fiscal_132195_initial_moku_reference'),
          rowsForNode(supplementary),
        ])
      const initialLines = allInitialLines.filter((r: any) =>
        r.dataset_id.startsWith('132195:2023:')
      )
      expect(references.map((r: any) => Number(r.amount_initial)).sort()).toEqual([
        30000000, 34553000,
      ])
      expect(references).toHaveLength(2)
      expect(references.every((r) => r.superseded_by_full_initial_detail)).toBe(true)
      expect(initialLines.length).toBeGreaterThan(2)
      expect(initialLines.some((r) => r.dataset_id === `132195:2023:expenditure:budget:${initial}:expenditure-detail`)).toBe(false)
      const itemIds = new Set(items.map((r) => r.budget_item_id))
      expect(initialLines.every((r) => itemIds.has(r.budget_item_id))).toBe(true)
      expect(initialLines.every((r) => r.dataset_id.startsWith('132195:2023:expenditure:'))).toBe(true)
      expect(budgetChanges.every((r) => r.dataset_id.startsWith('132195:2023:expenditure:'))).toBe(true)
      expect(
        money
          .filter((r: any) => r.record_kind === 'initial')
          .map((r: any) => r.initial_yen)
          .sort()
      ).toEqual([30000000, 34553000])
      expect(
        money.filter((r) => r.record_kind === 'change')
          .map((r: any) => r.delta_yen)
          .sort((a: number, b: number) => a - b)
      ).toEqual([-115000000, 1980000, 148300000])
      // The printed project/setsu rows replace the pilot moku changes in additive marts.
      const projectChanges = details.filter((r) =>
        r.kan_code === '7' && r.kou_code === '1' && r.moku_code === '2'
      )
      expect(projectChanges.map((r) => Number(r.delta_yen)).sort((a, b) => a - b)).toEqual([-115000000, 3300000, 145000000])
      for (const detail of projectChanges) {
        const matching = budgetChanges.filter((r) => r.dataset_id === detail.dataset_id && r.source_row === detail.source_row)
        expect(matching).toHaveLength(1)
        expect(Number(matching[0]!.amount_delta)).toBe(Number(detail.delta_yen))
      }
      expect(budgetChanges.some((r) => r.dataset_id === `132195:2023:expenditure:supplementary:${issue3}:expenditure-detail`)).toBe(false)
      expect(links).toHaveLength(10)
      expect(new Set(links.map((r: any) => r.settlement_line_id)).size).toBe(10)
      for (const r of money) {
        expect(r.fiscal_line_id).toContain(r.origin_sha256)
        expect(r.page_number).toBeGreaterThan(0)
      }
    }
  )

  test(
    'AC3: local UI shows both year-end differences and limits',
    { timeout: 60_000, tags: ['history-ac3'] },
    async ({ app, browser }) => {
      const { evaluate, settle } = session(browser)

      await evaluate(
        `(()=>{document.querySelector('.budget-reconciliation').open=true;return true})()`
      )
      const text = await settle(
        `document.querySelector('.budget-reconciliation[open]')?.innerText`
      )
      for (const amount of [
        '34,553,000',
        '33,300,000',
        '67,853,000',
        '68,814,000',
        '961,000',
        '66,261,365',
        '30,000,000',
        '1,980,000',
        '31,980,000',
        '23,761,662',
        '-8,218,338',
      ])
        expect(text).toContain(amount)
      expect(text).toContain('歳出の節は未確認')
      expect(text).toContain('予算全体の復元を示さない')
      expect(
        await evaluate(
          `document.querySelectorAll('.budget-reconciliation tbody tr').length`
        )
      ).toBe(2)
    }
  )

  test(
    'View AC2: raw and staging initial rows link without another document',
    { timeout: 60_000, tags: ['view-initial-rows'] },
    async ({ app, browser }) => {
      const { settle, edge, selectRow, selection } = session(browser)

      await edge(raw, stage)
      await expect(browser.locator('.io .rows tr.rowhit').first()).toBeVisible()
      await selectRow(0, `${initial}|expenditure-detail|1`, 8)
      await settle(
        `document.querySelectorAll('.io .rows tr.rowsel').length===2`
      )
      const selected = await selection()
      expect(selected).toHaveLength(2)
      expect(selected.every((r: any) => r.key.includes(initial))).toBe(true)
      expect(selected[0].text).toContain('34,553')
    }
  )

  test(
    'View AC2: supplement and mart isolate issue 3 from issue 6 of same target',
    { timeout: 60_000, tags: ['view-change-rows'] },
    async ({ app, browser }) => {
      const { settle, edge, selectRow, selection } = session(browser)

      const inputRows = await rows(app.baseUrl!, supplementary)
      const position = inputRows.findIndex((r) =>
        r.origin_sha256 === issue3 && r.source_row === 48
      )
      expect(position).toBeGreaterThanOrEqual(0)
      await edge(supplementary, changes)
      await settle(`document.querySelectorAll('.io .rows tr.rowhit').length>=8`)
      await selectRow(0, `${issue3}|supplementary-expenditure-project-setsu|48`, position)
      await settle(
        `document.querySelectorAll('.io .rows tr.rowsel').length===2`
      )
      const selected = await selection()
      expect(selected).toHaveLength(2)
      expect(selected.every((r: any) => r.key.includes(issue3))).toBe(true)
      expect(selected.map((r: any) => r.text).join(' ')).not.toContain(
        '-115000000'
      )
    }
  )

  test(
    'View AC2/3: rotated original PDF maps to only the supplement row and shows scope',
    { timeout: 60_000, tags: ['view-rotated-pdf'] },
    async ({ app, browser }) => {
      const base = app.baseUrl!
      const { evaluate, settle, edge, selection } = session(browser)

      await edge(
        `source.fudoki.raw_132195.doc_${issue3.slice(0, 12)}.origin`,
        raw
      )
      await expect(browser.locator('.pdfpager input')).toBeVisible()
      await evaluate(
        `(()=>{const e=document.querySelector('.pdfpager input');e.value='20';e.dispatchEvent(new FocusEvent('focusout',{bubbles:true}));return true})()`
      )
      await settle(
        `Boolean(document.querySelector('.pdfpage img[alt="PDF p.20"]')&&document.querySelector('.wspan[data-sr*="${issue3}"][data-sr$="|18"]'))`
      )
      await evaluate(
        `(()=>{const word=[...document.querySelectorAll('.wspan[data-sr]')].find(e=>e.getAttribute('data-sr').endsWith('|18')&&e.textContent.startsWith('148,30'));if(!word)throw new Error('supplement word absent');word.dispatchEvent(new MouseEvent('click',{bubbles:true}));return true})()`
      )
      await settle(
        `document.querySelectorAll('.pdfpage .hit').length===1&&document.querySelectorAll('.io .rows tr.rowsel').length===1`
      )
      const selected = await selection()
      expect(selected[0].key).toContain(`${issue3}|expenditure-detail|18`)
      expect(selected[0].text).toContain('148,300')
      const geometry = await evaluate(
        `(()=>{const img=document.querySelector('.pdfpage img'),hit=document.querySelector('.pdfpage .hit'),word=[...document.querySelectorAll('.wspan[data-sr]')].find(e=>e.getAttribute('data-sr').endsWith('|18')&&e.textContent.startsWith('148,30'));const h=hit.getBoundingClientRect(),w=word.getBoundingClientRect(),i=img.getBoundingClientRect();return {width:img.naturalWidth,height:img.naturalHeight,overlapsCorrectWord:h.left<=w.right&&h.right>=w.left&&h.top<=w.bottom&&h.bottom>=w.top,insideImage:h.left>=i.left&&h.right<=i.right&&h.top>=i.top&&h.bottom<=i.bottom}})()`
      )
      const indexResponse = await fetch(new URL('/local/pdf-index', base))
      expect(indexResponse.status).toBe(200)
      const index = await indexResponse.json()
      const docId = Object.keys(index.docs).find(
        (id) => index.docs[id].sha256 === issue3
      )!
      const pageResponse = await fetch(
        new URL(`/local/pdf/${docId}/p20.json`, base)
      )
      expect(pageResponse.status).toBe(200)
      const pageData = await pageResponse.json()
      expect(pageData.w).toBe(842)
      expect(pageData.h).toBe(595)
      expect(geometry.width / geometry.height).toBeCloseTo(
        pageData.w / pageData.h,
        2
      )
      expect(geometry.width).toBeGreaterThan(geometry.height)
      expect(geometry.overlapsCorrectWord).toBe(true)
      expect(geometry.insideImage).toBe(true)
      await evaluate(
        `(()=>{document.querySelectorAll('.io details').forEach(e=>e.open=true);return true})()`
      )
      const details = await evaluate(`document.querySelector('.io').innerText`)
      expect(details).toContain('千円')
      expect(details).toContain('補正')
      expect(details).not.toContain('復元: false')
    }
  )

  test(
    'AC2/4 and view warning scopes: focused regressions pass',
    { timeout: 60_000, tags: ['focused-regressions'] },
    async ({ app, browser }) => {
      const args = [
        'test',
        'pipeline/verify/report/fiscal/budget-reconciliation.test.ts',
        'pipeline/verify/report/common.test.ts',
        'pipeline/verify/view/src/lib/history-keys.test.ts',
        'pipeline/verify/view/src/components/pipeline/checks.test.tsx',
      ]
      mkdirSync('.e2e/logs', { recursive: true })
      try {
        const { stdout, stderr } = await run('bun', args)
        writeFileSync('.e2e/logs/focused-regressions.log', stdout + stderr)
      } catch (error) {
        const failure = error as { stdout?: string; stderr?: string }
        writeFileSync(
          '.e2e/logs/focused-regressions.log',
          (failure.stdout ?? '') + (failure.stderr ?? '')
        )
        throw error
      }
    }
  )
})
