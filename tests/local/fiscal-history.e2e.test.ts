import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from 'bun:test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const base = 'http://127.0.0.1:5174'
const sha = execFileSync('git', ['rev-parse', 'HEAD'], {
  encoding: 'utf8',
}).trim()
const output = resolve('.agent/pr-e2e', `${sha.slice(0, 12)}-${Date.now()}`)
const executable =
  process.env.ORCA_CLI_COMMAND ??
  (process.env.ORCA_DEV_REPO_ROOT
    ? 'orca-dev'
    : process.platform === 'linux'
      ? 'orca-ide'
      : 'orca')
const results: {
  criterion: string
  status: string
  evidence?: unknown
  error?: string
}[] = []
let page: string | undefined
mkdirSync(output, { recursive: true })

function cli(args: string[]) {
  const response = JSON.parse(
    execFileSync(executable, [...args, '--json'], {
      encoding: 'utf8',
      maxBuffer: 32 * 1024 * 1024,
    }),
  )
  if (!response.ok) throw new Error(JSON.stringify(response))
  return response.result
}
function evaluate(expression: string) {
  const value = cli([
    'eval',
    '--page',
    page!,
    '--expression',
    expression,
  ]).result
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}
function settle(expression: string) {
  return evaluate(
    `new Promise((resolve,reject)=>{const condition=()=>(${expression});let observer;const done=()=>{const value=condition();if(value){observer?.disconnect();clearTimeout(deadline);resolve(value)}};const deadline=setTimeout(()=>{observer?.disconnect();reject(new Error('DOM condition timed out'))},20000);observer=new MutationObserver(done);observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true});done()})`,
  )
}
async function screenshot(name: string) {
  const shot = cli(['screenshot', '--page', page!])
  writeFileSync(
    resolve(output, `${name}.png`),
    Buffer.from(shot.data.replace(/^data:image\/\w+;base64,/, ''), 'base64'),
  )
}
async function criterion(id: string, action: () => Promise<unknown>) {
  try {
    const evidence = await action()
    results.push({ criterion: id, status: 'pass', evidence })
    writeFileSync(
      resolve(output, `${id}.json`),
      JSON.stringify(evidence, null, 2),
    )
    await screenshot(id)
  } catch (error) {
    results.push({ criterion: id, status: 'fail', error: String(error) })
    try {
      writeFileSync(
        resolve(output, `${id}-failure-state.json`),
        JSON.stringify(
          evaluate(
            `({hits:document.querySelectorAll('.pdfpage .hit').length, selected:[...document.querySelectorAll('.io .rows tr.rowsel')].map(e=>e.getAttribute('data-sr')),scrolls:[...document.querySelectorAll('.io .rows')].map(e=>({top:e.scrollTop,first:e.querySelector('tr[data-sr]')?.getAttribute('data-sr')}))})`,
          ),
          null,
          2,
        ),
      )
      await screenshot(`${id}-failure`)
    } catch {}
    throw error
  }
}
async function rows(node: string) {
  const query = new URLSearchParams({
    node,
    code: '132195',
    year: '2023',
    dir: 'expenditure',
  })
  const response = await fetch(`${base}/local/rows?${query}`)
  expect(response.status).toBe(200)
  const table = await response.json()
  expect(table.kind).toBe('table')
  return table.rows.map((r: unknown[]) =>
    Object.fromEntries(table.columns.map((c: string, i: number) => [c, r[i]])),
  )
}
function edge(from: string, to: string) {
  evaluate(
    `(()=>{const e=document.querySelector(${JSON.stringify(`[data-edge="${from}|${to}"]`)});if(!e)throw new Error('missing lineage edge');e.dispatchEvent(new MouseEvent('click',{bubbles:true}));return true})()`,
  )
}
function selectRow(side: number, suffix: string, position: number) {
  evaluate(
    `(()=>{const box=document.querySelectorAll('.io .rows')[${side}];box.scrollTop=${position * 24};box.dispatchEvent(new Event('scroll'));return true})()`,
  )
  settle(
    `Boolean([...(document.querySelectorAll('.io .rows')[${side}]).querySelectorAll('tr[data-sr]')].find(e=>e.getAttribute('data-sr').includes(${JSON.stringify(suffix)})))`,
  )
  evaluate(
    `(()=>{const row=[...document.querySelectorAll('.io .rows')[${side}].querySelectorAll('tr[data-sr]')].find(e=>e.getAttribute('data-sr').includes(${JSON.stringify(suffix)}));row.dispatchEvent(new MouseEvent('click',{bubbles:true}));return true})()`,
  )
}
function selection() {
  return evaluate(
    `([...document.querySelectorAll('.io .rows tr.rowsel')].map(e=>({key:e.getAttribute('data-sr'),text:e.innerText})))`,
  )
}
const raw = 'source.fudoki.raw_132195_history.data'
const stage = 'model.fudoki.stg_132195__budget_history'
const history = 'model.fudoki.int_fiscal_budget_history'
const changes = 'model.fudoki.fiscal_expenditure_budget_changes'
const issue3 =
  'e322f20a1bfc32099a3271dad9fa38d23c7c45d9f0ce1b7cc45eb8f258a6817f'
const initial =
  '21fc642dc4ca89acab6ea18632d6ee8539949272ecba65c78231a37a71ba6ee9'

beforeAll(async () => {
  expect(process.env.E2E_TELEMETRY_DISABLED).toBe('1')
  expect((await fetch(`${base}/pipeline/132195/`)).status).toBe(200)
  page = cli([
    'tab',
    'create',
    '--url',
    `${base}/pipeline/132195/`,
  ]).browserPageId
  cli(['wait', '--page', page!, '--selector', '[data-edge]'])
})
beforeEach(() => {
  cli(['goto', '--page', page!, '--url', `${base}/pipeline/132195/`])
  cli(['wait', '--page', page!, '--selector', '[data-edge]'])
})
afterAll(() => {
  let cleanup: unknown = { status: 'not-created' }
  try {
    if (page) {
      cli(['tab', 'close', '--page', page])
      const tabs = cli(['tab', 'list']).tabs
      expect(tabs.some((tab: any) => tab.browserPageId === page)).toBe(false)
      cleanup = { status: 'closed-and-absent', page }
    }
  } catch (error) {
    cleanup = { status: 'failed', error: String(error) }
    throw error
  } finally {
    writeFileSync(
      resolve(output, 'report.json'),
      JSON.stringify(
        {
          sha,
          base,
          engine: 'Orca embedded browser',
          telemetryDisabled: true,
          e2eDevWeb: {
            status: 'unavailable',
            reason:
              'All published engine versions are inside the required 7-day cooldown; no dependency installed.',
          },
          data: 'Adopted read-only fixed inputs; no test-created fiscal records',
          results,
          cleanup,
        },
        null,
        2,
      ),
    )
    console.log(`PRD E2E report: ${output}/report.json`)
  }
})

describe('狛江市2023年度二目の補正予算', () => {
  test(
    'AC1: adopted inputs reach initial, changes and settlement-link marts',
    async () =>
      criterion('history-ac1', async () => {
        const [money, budgetChanges, links, allInitialLines, items] =
          await Promise.all([
            rows(history),
            rows(changes),
            rows('model.fudoki.fiscal_expenditure_settlement_links'),
            rows('model.fudoki.fiscal_initial_expenditure_budget_lines'),
            rows('model.fudoki.fiscal_expenditure_budget_items'),
          ])
        const initialLines = allInitialLines.filter((r: any) =>
          r.dataset_id.startsWith('132195:2023:'),
        )
        expect(initialLines.map((r: any) => Number(r.amount)).sort()).toEqual([
          30000000, 34553000,
        ])
        expect(items).toHaveLength(2)
        expect(
          items.every(
            (r: any) =>
              r.expenditure_setsu_id === null &&
              r.line_granularity === 'origin_line',
          ),
        ).toBe(true)
        expect(
          money
            .filter((r: any) => r.record_kind === 'initial')
            .map((r: any) => r.initial_yen)
            .sort(),
        ).toEqual([30000000, 34553000])
        expect(
          budgetChanges
            .map((r: any) => r.amount_delta)
            .sort((a: number, b: number) => a - b),
        ).toEqual([-115000000, 1980000, 148300000])
        expect(links).toHaveLength(10)
        expect(new Set(links.map((r: any) => r.settlement_line_id)).size).toBe(
          10,
        )
        for (const r of money) {
          expect(r.fiscal_line_id).toContain(r.origin_sha256)
          expect(r.page_number).toBeGreaterThan(0)
        }
        return {
          initialLines,
          items,
          initial: money.filter((r: any) => r.record_kind === 'initial'),
          changes: budgetChanges,
          settlementLinks: links,
        }
      }),
    60000,
  )

  test(
    'AC3: local UI shows both year-end differences and limits',
    async () =>
      criterion('history-ac3', async () => {
        evaluate(
          `(()=>{document.querySelector('.budget-reconciliation').open=true;return true})()`,
        )
        const text = settle(
          `document.querySelector('.budget-reconciliation[open]')?.innerText`,
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
          evaluate(
            `document.querySelectorAll('.budget-reconciliation tbody tr').length`,
          ),
        ).toBe(2)
        return { text }
      }),
    60000,
  )

  test(
    'View AC2: raw and staging initial rows link without another document',
    async () =>
      criterion('view-initial-rows', async () => {
        edge(raw, stage)
        cli(['wait', '--page', page!, '--selector', '.io .rows tr.rowhit'])
        selectRow(0, `${initial}|expenditure-detail|1`, 8)
        settle(`document.querySelectorAll('.io .rows tr.rowsel').length===2`)
        const selected = selection()
        expect(selected).toHaveLength(2)
        expect(selected.every((r: any) => r.key.includes(initial))).toBe(true)
        expect(selected[0].text).toContain('34,553')
        return { selected }
      }),
    60000,
  )

  test(
    'View AC2: supplement and mart isolate issue 3 from issue 6 of same target',
    async () =>
      criterion('view-change-rows', async () => {
        edge(history, changes)
        settle(`document.querySelectorAll('.io .rows tr.rowhit').length>=8`)
        selectRow(0, `${issue3}|expenditure-detail|18`, 4)
        settle(`document.querySelectorAll('.io .rows tr.rowsel').length===2`)
        const selected = selection()
        expect(selected).toHaveLength(2)
        expect(selected.every((r: any) => r.key.includes(issue3))).toBe(true)
        expect(selected.map((r: any) => r.text).join(' ')).not.toContain(
          '-115000000',
        )
        return { selected }
      }),
    60000,
  )

  test(
    'View AC2/3: rotated original PDF maps to only the supplement row and shows scope',
    async () =>
      criterion('view-rotated-pdf', async () => {
        edge(`source.fudoki.raw_132195.doc_${issue3.slice(0, 12)}.origin`, raw)
        cli(['wait', '--page', page!, '--selector', '.pdfpager input'])
        evaluate(
          `(()=>{const e=document.querySelector('.pdfpager input');e.value='20';e.dispatchEvent(new FocusEvent('focusout',{bubbles:true}));return true})()`,
        )
        settle(
          `Boolean(document.querySelector('.pdfpage img[alt="PDF p.20"]')&&document.querySelector('.wspan[data-sr*="${issue3}"][data-sr$="|18"]'))`,
        )
        evaluate(
          `(()=>{const word=[...document.querySelectorAll('.wspan[data-sr]')].find(e=>e.getAttribute('data-sr').endsWith('|18')&&e.textContent.startsWith('148,30'));if(!word)throw new Error('supplement word absent');word.dispatchEvent(new MouseEvent('click',{bubbles:true}));return true})()`,
        )
        settle(
          `document.querySelectorAll('.pdfpage .hit').length===1&&document.querySelectorAll('.io .rows tr.rowsel').length===1`,
        )
        const selected = selection()
        expect(selected[0].key).toContain(`${issue3}|expenditure-detail|18`)
        expect(selected[0].text).toContain('148,300')
        const geometry = evaluate(
          `(()=>{const img=document.querySelector('.pdfpage img'),hit=document.querySelector('.pdfpage .hit'),word=[...document.querySelectorAll('.wspan[data-sr]')].find(e=>e.getAttribute('data-sr').endsWith('|18')&&e.textContent.startsWith('148,30'));const h=hit.getBoundingClientRect(),w=word.getBoundingClientRect(),i=img.getBoundingClientRect();return {width:img.naturalWidth,height:img.naturalHeight,overlapsCorrectWord:h.left<=w.right&&h.right>=w.left&&h.top<=w.bottom&&h.bottom>=w.top,insideImage:h.left>=i.left&&h.right<=i.right&&h.top>=i.top&&h.bottom<=i.bottom}})()`,
        )
        const index = await (await fetch(`${base}/local/pdf-index`)).json()
        const docId = Object.keys(index.docs).find(
          (id) => index.docs[id].sha256 === issue3,
        )!
        const pageData = await (
          await fetch(`${base}/local/pdf/${docId}/p20.json`)
        ).json()
        expect(pageData.w).toBe(842)
        expect(pageData.h).toBe(595)
        expect(geometry.width / geometry.height).toBeCloseTo(
          pageData.w / pageData.h,
          2,
        )
        expect(geometry.width).toBeGreaterThan(geometry.height)
        expect(geometry.overlapsCorrectWord).toBe(true)
        expect(geometry.insideImage).toBe(true)
        evaluate(
          `(()=>{document.querySelectorAll('.io details').forEach(e=>e.open=true);return true})()`,
        )
        const details = evaluate(`document.querySelector('.io').innerText`)
        expect(details).toContain('千円')
        expect(details).toContain('補正')
        expect(details).not.toContain('復元: false')
        return {
          selected,
          geometry,
          pdfDimensions: { w: pageData.w, h: pageData.h },
          details,
        }
      }),
    60000,
  )

  test(
    'AC2/4 and view warning scopes: focused regressions pass',
    async () =>
      criterion('focused-regressions', async () => {
        const args = [
          'test',
          'pipeline/verify/report/fiscal/budget-reconciliation.test.ts',
          'pipeline/verify/report/common.test.ts',
          'pipeline/verify/view/src/lib/history-keys.test.ts',
          'pipeline/verify/view/src/components/pipeline/checks.test.tsx',
        ]
        const process = Bun.spawn(['bun', ...args], {
          stdout: 'pipe',
          stderr: 'pipe',
        })
        const [stdout, stderr, status] = await Promise.all([
          new Response(process.stdout).text(),
          new Response(process.stderr).text(),
          process.exited,
        ])
        writeFileSync(
          resolve(output, 'focused-regressions.log'),
          stdout + stderr,
        )
        expect(status).toBe(0)
        return {
          command: ['bun', ...args],
          status,
          log: 'focused-regressions.log',
          verification:
            'Time-boundary, missing-data, duplicate/M:N and cross-document keys; warning fixtures, not live warnings.',
        }
      }),
    60000,
  )
})
