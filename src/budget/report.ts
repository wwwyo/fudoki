/**
 * # パイプライン報告
 *
 * 変換が正しく動いたかを**人が判定できる**ようにするための出力物。
 * 各段について「何が入って何が出たか」「1行がどう変わったか」「何を検査して結果はどうか」の3つを出す。
 * 差分が0でない段があれば、そこが疑うべき場所になる。
 */
import { CUSTOM_COLUMN_TYPES } from './columns'
import { COFOG_DIVISIONS, COFOG_SOURCE, COFOG_VERSION, CONSOLIDATION_SCOPE, RULE_IDS } from './cofog'
import type { CanonicalTable, Row } from './load'
import { NOT_YET_RECONCILED } from './published/mitaka-2024'
import type { BudgetSource } from './source'
import type { DerivedTable } from './transform'
import type { Check } from './verify'

/** `data/observations/mitaka-budget-years.json` の形。生成側と読む側で1箇所に置く */
export type YearSurvey = {
  caveat: string
  observations: {
    label: string
    direction: string
    rows?: number
    funds?: string[]
    coverageNote: string | null
    compatible: boolean | null
    basis: string
    sha256?: string
    fetchedAt: string
  }[]
}

const yen = (n: number) => n.toLocaleString('ja-JP')
const mark = (ok: boolean) => (ok ? '✓' : '✗')

/**
 * 変換の各要素を3つに分ける。**2団体目で何を確かめるかを先に書いておく。**
 * 「再利用可能と判明した」は1団体では言えないので、判定できないものは判定できないと書く。
 */
const PORTABILITY: { element: string; kind: '再利用の候補' | '三鷹市に固有' | '一般性を判定できない'; verifyNext: string }[] = [
  { element: 'CKAN からのリソース解決と証跡の記録（Extract）', kind: '再利用の候補', verifyNext: '東京都カタログ以外（BODIK・独自 DCAT）でも同じ形で引けるか' },
  { element: '完全修飾パスから識別子を導く方式', kind: '再利用の候補', verifyNext: '階層の深さが違う団体でも一意になるか。狛江市は事業階層が3段ある' },
  { element: '原典の値と単位を別列に残したうえで円へ正規化する方式', kind: '再利用の候補', verifyNext: '単位が円の団体（狛江市は「予算額(円)」）で倍率1が素通りするか' },
  { element: '検査の並べ方（多重集合一致・従属関係・複合主キー・公表値突合）', kind: '再利用の候補', verifyNext: '公表資料が款別を載せない団体でも代替の外部突合が立つか' },
  { element: 'COFOG の2軸（分類 / 連結）と規則エンジンの形', kind: '再利用の候補', verifyNext: '規則の本数が団体ごとに増えるか、款の語彙が共通で使い回せるか' },
  { element: '「事項」を事業階層として宣言すること', kind: '三鷹市に固有', verifyNext: '狛江市は「大事業 / 中事業 / 小事業」。宣言の粒度が団体ごとに違う前提で足りるか' },
  { element: '歳入の細々節を `0` で埋めるプレースホルダ', kind: '三鷹市に固有', verifyNext: '他団体が空文字・全角ゼロ・ハイフンなど別の表現を使うか' },
  { element: '2桁コード + 名称という1セルの書式', kind: '三鷹市に固有', verifyNext: '桁数が違う団体、コードと名称が別列の団体でセル分解の宣言が要るか' },
  { element: '歳出と歳入の合計一致という検算', kind: '三鷹市に固有', verifyNext: '当初予算以外や企業会計を持つ団体では成立しない。取得元ごとの設定で切れているか' },
  { element: '款 → COFOG ディビジョンの対応そのもの', kind: '一般性を判定できない', verifyNext: '款の名称は法定なので共通のはずだが、項・目の名称は団体差がある。項以下の規則が何本必要になるか' },
  { element: '事項が1つの事業に対応するという前提', kind: '一般性を判定できない', verifyNext: '複数の活動をまとめた事項や管理的な費目が混ざっていないか。2団体目で概念として確定させる' },
  { element: '`fin-source:generic:level4〜6` という標準の拡張', kind: '一般性を判定できない', verifyNext: '他団体の歳入も6階層か。3階層で足りるなら拡張自体をやめられる' },
]

/**
 * 実装中に確定できなかったこと、および設計文書と実データが食い違った点。
 * **推測で埋めずにここへ残す。**
 */
const CAVEATS: { topic: string; body: string }[] = [
  {
    topic: '事項を事業として扱う妥当性が未検証（Design Doc Caveats 1）',
    body:
      '名称を持つことは、その区分が1つの事業に対応することの証明にならない。複数の活動をまとめた事項や管理的な費目が含まれうる。' +
      '自治体横断の「事業」概念として確定するのは2団体目以降とする。現状は `activity:generic:program` に置いてあるが、これは候補としての割り当てである。',
  },
  {
    topic: 'COFOG の割り当てが款の単位で成立するかは部分的（Design Doc Caveats 2）',
    body:
      '実データを通した結果、**款だけでは決まらない款が実在した**。衛生費（保健衛生費 → 07 / 清掃費 → 05）と土木費と教育費は項へ、' +
      '公債費（元金 → 対象外 / 利子 → 01）と都市計画費と生涯学習費は目へ下げて決着した。どこまで下げれば決まるかは報告の「款で決まらず、下の単位まで下げたもの」を見ること。',
  },
  {
    topic: 'PRD の「938件の事項」は事項の件数ではない',
    body:
      '実測すると、938 は**事項のセル文字列（コード + 名称）の異なり数**であって、階層としての事項の件数ではない。' +
      '完全修飾で数えると全会計 996 件・一般会計 913 件、名称の異なり数は全会計 918 件・一般会計 856 件になる。' +
      'ただし「すべて名称を持つ」という主張自体は正しい（名称が空の事項は0件）。三鷹市を選んだ判断は変わらないが、数字は置き換える必要がある。',
  },
  {
    topic: 'Design Doc は歳入を6階層としていたが、原典は7階層',
    body:
      '原典の歳入は会計/款/項/目/節/細節に加えて**細々節を持つ**。821 行中 18 行が実際に使っており、細々節を落とすと識別子が7組衝突する。' +
      'Design Doc の記述ではなく実物の列で判定した（パーサ設計の原則3）。',
  },
  {
    topic: '識別子はコードのパスでは作れなかった',
    body:
      'Design Doc は「`款01/項03/目01` の形で連結する」としていたが、三鷹市の細々節は**同じ節の下でコードを再利用する**（実測 710 箇所・1,615 行）。' +
      'コードのパスでは 5,613 行が 4,708 通りにしかならない。そこでパスの構成要素を**セル全文（コード + 名称）**に取った。' +
      '副作用として、自治体が名称を直すと識別子が変わる。コードだけなら耐えられたはずの変更なので、これは失ったものである。',
  },
  {
    topic: '仕様が正準と宣言する taxonomy の URL が 404',
    body:
      '`https://specs.frictionlessdata.io/taxonomies/fiscal/budgets.json` は 404 を返す（2026-08-16 実測）。' +
      'ColumnType の一覧を機械可読な形で参照する経路が存在しないため、仕様の原文（Markdown）から起こして `src/budget/taxonomy/` に取り込み、fudoki 側で保守する。' +
      'descriptor の `columnTypes` は仕様どおりこの URL を指しているが、**利用者がこれを辿っても取得できない**。',
  },
  {
    topic: '`fin-source:generic:level4〜6` は標準の名前空間を fudoki が拡張したもの',
    body:
      '歳入の階層は6段あるが、標準の `fin-source:generic` は level3 までしか定義が無い。`prior` を繋いで順序が保たれるよう同じ命名規則で拡張した。' +
      '標準側が後から level4 を別の意味で定義すると衝突する。FDP は 2024-03 で更新が止まっているため当面は起きないと見ているが、独自の名前空間に逃がす選択肢もあった。',
  },
  {
    topic: '繰出金と繰入金は行どうしが1対1に対応しない',
    body:
      '歳出の繰出金と歳入の繰入金は細々節の切り方が違うため、行の対応は N 対 M になる。金額が厳密に一致するのは**会計の対どうしの合計**で、そこは5対すべてで一致した。' +
      '各行の `cofog_counterpart_ids` には受け皿側の該当行の識別子を並べてあるが、これは「その行1件の相手」ではなく**相手のグループ**である。',
  },
  {
    topic: '特別会計は外部資料で裏づけていない',
    body:
      '施政方針・予算概要は一般会計の款別までしか載せていない。特別会計の款別を突合するには予算書（別資料）が要る。' +
      '現状の根拠は歳出と歳入の会計別合計が一致することだけで、これは原典の内部整合であって外部からの裏づけではない。',
  },
  {
    topic: '河川費と生涯学習費の割り当ては判断の幅がある',
    body:
      'COFOG は治水を明示的に置いていないため、河川費（15,852千円）は 05 環境保護に寄せたが 04 経済業務にも読める。' +
      '生涯学習費のうち図書館費は COFOG 08.2 が図書館を明示的に含むため 08 に置き、それ以外（生涯学習総務・青少年育成・生涯学習センター）は社会教育として 09 に置いた。' +
      'いずれも根拠を `cofog_basis` に書いてあるので、判断を変えたければそこを見て変えられる。',
  },
]

function tally<T>(rows: readonly T[], key: (r: T) => string, value: (r: T) => number) {
  const m = new Map<string, { count: number; sum: number }>()
  for (const r of rows) {
    const k = key(r)
    const acc = m.get(k) ?? { count: 0, sum: 0 }
    acc.count++
    acc.sum += value(r)
    m.set(k, acc)
  }
  return m
}

/** 1行が入力から出力へどう変わったかを、実物で見せる */
function walkthrough(table: CanonicalTable, source: BudgetSource): string {
  const row = table.rows[0]!
  const levels = table.levels
  const raw = [...levels.map((l) => row[`${l.key}_source`]), row.source_amount].join(',')
  const lines = [
    '```',
    `原典  ${raw}`,
    '```',
    '',
    '↓ Load',
    '',
    '| 出力の列 | 値 | どこから来たか |',
    '|---|---|---|',
    `| \`budget_line_id\` | \`${row.budget_line_id}\` | 団体コード・年度・direction・予算段階と、階層のセル全文から導出 |`,
    `| \`fiscal_year\` | ${row.fiscal_year} | **原典に無い**。${table.provenance.fiscalYearBasis} |`,
    `| \`direction\` | ${row.direction} | リソースごとの定数 |`,
    `| \`phase_id\` | ${row.phase_id} | 取得元の設定（${source.phase.label}） |`,
  ]
  for (const l of levels) {
    lines.push(`| \`${l.key}_code\` / \`${l.key}_label\` / \`${l.key}_source\` | \`${row[`${l.key}_code`]}\` / \`${row[`${l.key}_label`]}\` / \`${row[`${l.key}_source`]}\` | 原典の「${l.sourceColumn}」1セルを3列へ分離（連結すると原文へ戻る） |`)
  }
  lines.push(
    `| \`value\` | ${yen(Number(row.value))} | 原典の ${yen(Number(row.source_amount))}${source.amountUnit.label} を ×${source.amountUnit.multiplier} して円へ正規化 |`,
    `| \`source_amount\` / \`source_amount_unit\` | ${yen(Number(row.source_amount))} / ${row.source_amount_unit} | 原典の値と単位をそのまま保持 |`,
    `| \`source_row\` | ${row.source_row} | 原典の物理行番号 |`,
  )
  return lines.join('\n')
}

export function buildReport(args: {
  source: BudgetSource
  expenditure: CanonicalTable
  revenue: CanonicalTable
  derived: DerivedTable
  checks: Check[]
  outputs: { path: string; description: string; bytes: number }[]
  /** 他年度の互換性調査。無ければ節ごと出さない */
  yearSurvey: YearSurvey | null
}): string {
  const { source, expenditure, revenue, derived, checks, outputs } = args
  const tables = [expenditure, revenue]
  const failed = checks.filter((c) => !c.ok)
  const L: string[] = []

  L.push(`# パイプライン報告：${source.jurisdictionName} ${source.fiscalYearLabel}予算`)
  L.push('')
  L.push(`> このファイルは \`bun run build:budget\` が生成する。手で編集しない。`)
  L.push('')
  L.push(`- 団体: ${source.jurisdictionName}（全国地方公共団体コード \`${source.jurisdictionCode}\`）`)
  L.push(`- 年度: ${source.fiscalYearLabel}（西暦 ${source.fiscalYear}）`)
  L.push(`- 予算段階: ${source.phase.label}（\`${source.phase.id}\`）`)
  L.push(`- 収録範囲: ${source.coverageNote ?? '注記なし'}`)
  L.push(`- ライセンス: ${source.license.id} / 帰属表示「${source.attribution}」`)
  L.push('')
  L.push(`**検査 ${checks.length} 件中 ${checks.length - failed.length} 件が成功、${failed.length} 件が失敗。**`)
  L.push('')

  // ── Extract ────────────────────────────────────────
  L.push('## Extract')
  L.push('')
  L.push('原典を無加工で取得し、URL・HTTP status・SHA-256・取得時刻を証跡として残す。取得物はリポジトリに置かない。')
  L.push('')
  L.push('| direction | リソース名 | status | バイト数 | 行数 | 文字コード | SHA-256 | 取得時刻 |')
  L.push('|---|---|---|---|---|---|---|---|')
  for (const t of tables) {
    const p = t.provenance
    L.push(`| ${p.direction} | ${p.resourceName} | ${p.status} | ${yen(p.bytes)} | ${yen(p.rows)} | ${p.encoding} | \`${p.sha256}\` | ${p.fetchedAt} |`)
  }
  L.push('')
  L.push('| direction | 取得 URL | 列構成 |')
  L.push('|---|---|---|')
  for (const t of tables) L.push(`| ${t.provenance.direction} | ${t.provenance.requestUrl} | ${t.provenance.header.join(' / ')} |`)
  L.push('')
  L.push('**年度の由来**（原典に年度の列が無いため、解決の根拠を残す）')
  L.push('')
  for (const t of tables) L.push(`- ${t.provenance.direction}: ${t.provenance.fiscalYearBasis}`)
  L.push('')
  L.push('**検査**: HTTP status が 200 であること、先頭バイトが HTML でないこと、文字コードの判定結果。いずれも上表に出ている。')
  L.push('')

  // ── Load ──────────────────────────────────────────
  L.push('## Load')
  L.push('')
  L.push('原典1行を正本1行へ写す。**ここまでは原典に無い情報を足さない。**')
  L.push('')
  L.push('| direction | 入力（原典の行数） | 出力（正本の行数） | 差分 | 階層なしのセル | 想定外のセル |')
  L.push('|---|---|---|---|---|---|')
  for (const t of tables) {
    const diff = t.rows.length - t.provenance.rows
    L.push(`| ${t.provenance.direction} | ${yen(t.provenance.rows)} | ${yen(t.rows.length)} | ${diff === 0 ? '0' : `**${diff}**`} | ${yen(t.absentLevelCells)} | ${t.irregularCells.length} |`)
  }
  L.push('')
  L.push(`歳入の「階層なしのセル」は、細々節を持たない行を \`0\` で埋める三鷹市の表現。想定内なので件数だけ数える。`)
  L.push('')
  L.push('### 1行がどう変わったか（歳出の先頭行）')
  L.push('')
  L.push(walkthrough(expenditure, source))
  L.push('')
  L.push('### 階層の切り出し（それぞれ独立した切り口として取り出せる）')
  L.push('')
  for (const t of tables) {
    L.push(`**${t.provenance.direction}**`)
    L.push('')
    L.push('| 階層 | 語彙 | 異なり数 | ColumnType |')
    L.push('|---|---|---|---|')
    for (const l of t.levels) {
      const distinct = new Set(t.rows.map((r) => `${r[`${l.key}_code`]}`)).size
      const paths = new Set(t.rows.map((r) => t.levels.slice(0, t.levels.indexOf(l) + 1).map((p) => r[`${p.key}_source`]).join('/'))).size
      L.push(`| ${l.sourceColumn} | ${l.vocabulary === 'statutory' ? '地方自治法' : '三鷹市固有'} | コード ${distinct} / 完全修飾 ${paths} | \`${l.codeType}\` |`)
    }
    L.push('')
  }

  // ── Transform ──────────────────────────────────────
  L.push('## Transform')
  L.push('')
  L.push(`正本へ COFOG を割り当てて派生を作る。**ここで初めて fudoki の判断が入る。**`)
  L.push('')
  L.push(`- 版: ${COFOG_VERSION}（ディビジョンの値域 \`01\`〜\`10\`）`)
  L.push(`- コード表の取得元: [${COFOG_SOURCE.name}](${COFOG_SOURCE.url})`)
  L.push(`- 規則の本数: ${RULE_IDS.length}（\`src/budget/cofog.ts\`）`)
  L.push(`- 入力 ${yen(expenditure.rows.length)} 行 → 出力 ${yen(derived.rows.length)} 行（差分 ${derived.rows.length - expenditure.rows.length}）`)
  L.push('')
  L.push('> Budget Standard Taxonomy が提供するのは COFOG を格納する語彙だけで、')
  L.push('> **日本の予算科目から COFOG への対応そのものは仕様側に存在しない。** 以下は fudoki 固有の判断である。')
  L.push('')

  L.push('### 状態の分布')
  L.push('')
  L.push('分類の軸と連結の軸は別の問い。1つの排他的な状態に畳むと、分類できなかったものと、そもそも分類の対象でないものが混ざる。')
  L.push('')
  L.push('| 分類の軸 | 連結の軸 | ディビジョン | 行数 | 金額（円） |')
  L.push('|---|---|---|---|---|')
  const byState = tally(derived.rows, (r) => `${r.cofog_status}\t${r.cofog_consolidation}\t${r.cofog_division_code}`, (r) => Number(r.value))
  for (const k of [...byState.keys()].sort()) {
    const [status, cons, div] = k.split('\t')
    const v = byState.get(k)!
    L.push(`| ${status} | ${cons} | ${div ? `${div} ${COFOG_DIVISIONS[div]}` : '（空）'} | ${yen(v.count)} | ${yen(v.sum)} |`)
  }
  L.push('')

  L.push('### 款ごとの割当先・状態・根拠')
  L.push('')
  L.push('款は一般会計で12件。入力と出力を並べれば人が妥当性を判定できる規模である。')
  L.push('')
  L.push('| 会計 | 款 | 割当先 | 状態 | 決まった単位 | 金額（円） | 根拠 |')
  L.push('|---|---|---|---|---|---|---|')
  const byKan = tally(
    derived.rows,
    (r) => [r.fund_source, r.kan_source, r.cofog_division_code, r.cofog_status, r.cofog_decided_at_level, r.cofog_basis].join('\t'),
    (r) => Number(r.value),
  )
  for (const k of [...byKan.keys()].sort()) {
    const [fund, kan, div, status, level, basis] = k.split('\t')
    L.push(`| ${fund} | ${kan} | ${div ? `${div} ${COFOG_DIVISIONS[div]}` : '—' } | ${status} | ${level} | ${yen(byKan.get(k)!.sum)} | ${basis} |`)
  }
  L.push('')

  L.push('### 款で決まらず、下の単位まで下げたもの')
  L.push('')
  L.push('| 決まった単位 | 行数 | 金額（円） |')
  L.push('|---|---|---|')
  const byLevel = tally(derived.rows, (r) => String(r.cofog_decided_at_level), (r) => Number(r.value))
  for (const k of ['会計', '款', '項', '目', '節', '（規則なし）']) {
    const v = byLevel.get(k)
    if (v) L.push(`| ${k} | ${yen(v.count)} | ${yen(v.sum)} |`)
  }
  L.push('')

  L.push('### 連結の消去')
  L.push('')
  L.push(`連結の範囲: ${CONSOLIDATION_SCOPE}`)
  L.push('')
  L.push('| 出し手 | 受け皿 | 消去した金額（円） | 相手側の合計（円） | 一致 | 相手側の行数 |')
  L.push('|---|---|---|---|---|---|')
  for (const p of derived.consolidationPairs) {
    L.push(`| ${p.from} | ${p.to} | ${yen(p.eliminated)} | ${yen(p.counterpart)} | ${mark(p.eliminated === p.counterpart)} | ${p.counterpartIds.length} |`)
  }
  L.push('')
  L.push('> ⚠️ 歳出の繰出金と歳入の繰入金は**行と行が1対1に対応しない**（細々節の切り方が両者で違う）。')
  L.push('> 金額が厳密に一致するのは会計の対どうしの合計であり、上表がその突合結果である。')
  L.push('> 各行の `cofog_counterpart_ids` には、受け皿側の該当行の識別子を `;` 区切りで並べてある。')
  L.push('')

  L.push('### 分類不能と対象外の内訳')
  L.push('')
  L.push('**分類不能の割合の低さは合否に使わない。** 成立範囲を正直に調べることが目的であり、割合を目標にすると判断が歪む。')
  L.push('')
  L.push('| 状態 | 会計 | 款 | 金額（円） | 理由 |')
  L.push('|---|---|---|---|---|')
  const notAssigned = tally(
    derived.rows.filter((r) => r.cofog_status !== 'assigned'),
    (r) => [r.cofog_status, r.fund_source, r.kan_source, r.cofog_basis].join('\t'),
    (r) => Number(r.value),
  )
  for (const k of [...notAssigned.keys()].sort()) {
    const [status, fund, kan, basis] = k.split('\t')
    L.push(`| ${status} | ${fund} | ${kan} | ${yen(notAssigned.get(k)!.sum)} | ${basis} |`)
  }
  L.push('')

  // ── 検査 ──────────────────────────────────────────
  L.push('## 検査結果')
  L.push('')
  L.push('合計の突合だけに頼らない。1行の欠落と同額の行の重複は合計では相殺されて素通りするため、性質の異なる検査を並べる。')
  L.push('')
  L.push('| | 検査 | 結果 |')
  L.push('|---|---|---|')
  for (const c of checks) L.push(`| ${mark(c.ok)} | ${c.name} | ${c.detail} |`)
  L.push('')
  L.push(`### まだ突合していない範囲`)
  L.push('')
  L.push(`- **${NOT_YET_RECONCILED.scope}**`)
  L.push(`  - 理由: ${NOT_YET_RECONCILED.reason}`)
  L.push(`  - 出所の候補: ${NOT_YET_RECONCILED.wouldComeFrom}`)
  L.push(`  - 現在の根拠: ${NOT_YET_RECONCILED.currentEvidence}`)
  L.push('')

  // ── 他年度の互換性 ───────────────────────────────────
  if (args.yearSurvey) {
    const s = args.yearSurvey
    L.push('## 他年度との互換性（調査のみ。収録はしない）')
    L.push('')
    L.push(`出所: \`data/observations/mitaka-budget-years.json\`（\`bun run check:budget-years\` が生成）`)
    L.push('')
    L.push('| 年度 | direction | 行数 | 会計 | 収録範囲の注記 | 令和6年度と互換 | 判定根拠 | SHA-256 | 取得時刻 |')
    L.push('|---|---|---|---|---|---|---|---|---|')
    for (const o of s.observations) {
      L.push(
        `| ${o.label} | ${o.direction} | ${o.rows ?? '—'} | ${o.funds?.length ?? '—'} | ${o.coverageNote ?? 'なし'} | ${o.compatible === null ? '?' : mark(o.compatible)} | ${o.basis} | \`${(o.sha256 ?? '').slice(0, 16)}…\` | ${o.fetchedAt} |`,
      )
    }
    L.push('')
    L.push('**会計の範囲が年度で変わる。** 令和2年度以降は下水道事業会計を除いた5会計、平成28年度から令和元年度は下水道事業特別会計を含む6会計である。')
    L.push('リソース名の注記（`※下水道事業会計除く`）と、実際の会計一覧の差の両方で確認した。')
    L.push('')
    L.push(`> ⚠️ ${s.caveat}`)
    L.push('')
  }

  // ── 独自 ColumnType ─────────────────────────────────
  L.push('## 独自に定義した ColumnType')
  L.push('')
  L.push('標準の Budget Standard Taxonomy に無く、fudoki が定義したもの。descriptor の `columnTypes` にインラインで載せてある。')
  L.push('')
  L.push('| 名前 | dataType | unique | labelOf | なぜ独自定義が要るか |')
  L.push('|---|---|---|---|---|')
  for (const c of CUSTOM_COLUMN_TYPES) L.push(`| \`${c.name}\` | ${c.dataType} | ${c.unique ? '✓' : ''} | ${c.labelOf ? `\`${c.labelOf}\`` : ''} | ${c.why} |`)
  L.push('')

  // ── 展開 ──────────────────────────────────────────
  L.push('## 2団体目へ展開するときに何を確かめるか')
  L.push('')
  L.push('**「再利用可能と判明した」は1団体では言えない。** 判定できないものは判定できないと書く。')
  L.push('')
  for (const kind of ['再利用の候補', '三鷹市に固有', '一般性を判定できない'] as const) {
    L.push(`### ${kind}`)
    L.push('')
    L.push('| 要素 | 2団体目で確かめること |')
    L.push('|---|---|')
    for (const p of PORTABILITY.filter((x) => x.kind === kind)) L.push(`| ${p.element} | ${p.verifyNext} |`)
    L.push('')
  }

  // ── Caveats ────────────────────────────────────────
  L.push('## Caveats')
  L.push('')
  L.push('確定できなかったこと、および設計文書と実データが食い違った点。**推測で埋めずに残す。**')
  L.push('')
  for (const c of CAVEATS) {
    L.push(`### ${c.topic}`)
    L.push('')
    L.push(c.body)
    L.push('')
  }

  // ── 出力物 ─────────────────────────────────────────
  L.push('## 出力物')
  L.push('')
  L.push('| パス | バイト数 | 内容 |')
  L.push('|---|---|---|')
  for (const o of outputs) L.push(`| \`${o.path}\` | ${yen(o.bytes)} | ${o.description} |`)
  L.push('')
  L.push('---')
  L.push('')
  L.push(`生成: \`bun run build:budget\` / ${new Date().toISOString()}`)
  L.push('')
  return L.join('\n')
}

/** 報告に載せる集計は派生から導く。ここに焼き込まない */
export type { Row }
