/**
 * `web/pipeline.html` が読むデータを生成する。
 *
 * **中間物なので gitignore する**（正本は `data/packages/`、報告は `data/reports/` にあり、これはそこからの派生）。
 *
 * 埋め込みにするのは、ビューアを `web/` 配下だけで完結させるため。
 * リポジトリのルートを配信するサーバを別に立てると、成果物以外まで露出する。
 *
 *   bun run build:pipeline-view
 */
import { splitRows } from '../src/budget/extract'

const CODE = '132047'
const YEAR = '2024'
const root = new URL('../', import.meta.url).pathname
const OUT = `${root}web/_pipeline.js`

/** 画面が使う列だけ抜く。全列を積むと 3MB を超え、読ませる価値のない列まで運ぶことになる */
const KEEP_EXPENDITURE = [
  'budget_line_id', 'fiscal_year', 'phase_id', 'source_row',
  'fund_source', 'kan_source', 'kou_source', 'moku_source', 'jikou_source', 'setsu_source', 'saisaisetsu_source',
  'fund_label', 'kan_label', 'kou_label', 'moku_label', 'jikou_label', 'setsu_label', 'saisaisetsu_label',
  'value', 'source_amount', 'source_amount_unit',
  'cofog_division_code', 'cofog_division_label', 'cofog_status', 'cofog_consolidation', 'cofog_decided_at_level', 'cofog_basis', 'cofog_rule_id',
]
const KEEP_REVENUE = [
  'budget_line_id', 'fiscal_year', 'phase_id', 'source_row',
  'fund_source', 'kan_source', 'kou_source', 'moku_source', 'setsu_source', 'saisetsu_source', 'saisaisetsu_source',
  'fund_label', 'kan_label', 'kou_label', 'moku_label', 'setsu_label', 'saisetsu_label', 'saisaisetsu_label',
  'value', 'source_amount', 'source_amount_unit',
]

/**
 * 列名を1回だけ書き、行は値の配列で持つ。
 * 行ごとにキーを繰り返すと同じ列名が5,613回出て、ファイルの大半が列名になる。
 */
function columnar(csv: string, keep: readonly string[]) {
  const rows = splitRows(csv)
  const header = rows[0]!
  const idx = keep.map((k) => {
    const i = header.indexOf(k)
    if (i < 0) throw new Error(`列 ${k} が見つからない。build:budget を先に回すこと`)
    return i
  })
  return { columns: keep, rows: rows.slice(1).map((r) => idx.map((i) => r[i] ?? '')) }
}

const read = async (p: string) => {
  const f = Bun.file(p)
  if (!(await f.exists())) throw new Error(`${p} が無い。先に bun run build:budget を回すこと`)
  return f.text()
}

const report = JSON.parse(await read(`${root}data/reports/${CODE}-${YEAR}.json`))
const expenditure = columnar(await read(`${root}data/packages/${CODE}/${YEAR}/expenditure-cofog.csv`), KEEP_EXPENDITURE)
const revenue = columnar(await read(`${root}data/packages/${CODE}/${YEAR}/revenue.csv`), KEEP_REVENUE)

const payload = { code: CODE, year: YEAR, report, expenditure, revenue }
await Bun.write(OUT, `window.PIPELINE=${JSON.stringify(payload)};\n`)

const bytes = (await Bun.file(OUT).arrayBuffer()).byteLength
console.log(`${OUT} を生成した（歳出 ${expenditure.rows.length} 行 / 歳入 ${revenue.rows.length} 行 / ${(bytes / 1024 / 1024).toFixed(2)} MB）`)
