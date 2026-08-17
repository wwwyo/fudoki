/**
 * # パイプライン報告のデータ
 *
 * 変換が正しく動いたかを**人が判定できる**ようにするための出力物。
 * 各段について「何が入って何が出たか」「1行がどう変わったか」「何を検査して結果はどうか」の3つを持つ。
 * 差分が0でない段があれば、そこが疑うべき場所になる。
 *
 * ここが出すのは JSON だけで、読ませ方は `web/pipeline.html` が持つ。
 * **集計をこの1箇所に閉じ込めるため**で、表示側でも集計すると同じ数字が2通りに計算されて、
 * いずれ食い違ったまま気づかなくなる。
 */
import { CUSTOM_COLUMN_TYPES } from './columns'
import { COFOG_DIVISIONS, COFOG_SOURCE, COFOG_VERSION, CONSOLIDATION_SCOPE, RULE_IDS } from './cofog'
import type { Provenance } from './extract'
import type { CanonicalTable, Row } from './load'
import { NOT_YET_RECONCILED } from './published/mitaka-2024'
import type { BudgetSource } from './source'
import type { DerivedTable } from './transform'
import { buildTopology, type NodeKind, type Topology } from './topology'
import type { Direction } from './source'
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
/** 連結キーの区切り。名称にも金額にも現れない制御文字を使う */
const SEP = "\u001f"

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
      '公債費（元金 → 対象外 / 利子 → 01）と都市計画費と生涯学習費は目へ下げて決着した。どこまで下げれば決まるかは「款で決まらず、下の単位まで下げたもの」を見ること。',
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

// ── 報告のデータ ─────────────────────────────────────────

export type ReportData = {
  meta: {
    jurisdictionCode: string
    jurisdictionName: string
    fiscalYear: number
    fiscalYearLabel: string
    phase: { id: string; label: string }
    coverageNote: string | null
    license: BudgetSource['license']
    attribution: string
    landingPage: string
    generatedAt: string
  }
  summary: { total: number; passed: number; failed: number }
  /**
   * パイプラインの形。**画面はこれを描く**。
   * 段の名前と並びを画面側に直書きすると、パイプラインを変えても図が変わらなくなる。
   */
  topology: Topology
  extract: Provenance[]
  load: { direction: string; inputRows: number; outputRows: number; diff: number; absentLevelCells: number; irregularCells: number }[]
  walkthrough: { sourceLine: string; fields: { column: string; value: string; origin: string }[] }
  levels: { direction: string; items: { sourceColumn: string; vocabulary: string; distinctCodes: number; distinctPaths: number; columnType: string }[] }[]
  transform: {
    cofogVersion: string
    cofogSource: typeof COFOG_SOURCE
    ruleCount: number
    inputRows: number
    outputRows: number
    consolidationScope: string
    byState: { status: string; consolidation: string; division: string; divisionLabel: string; count: number; sum: number }[]
    byKan: { fund: string; kan: string; division: string; divisionLabel: string; status: string; decidedAtLevel: string; sum: number; basis: string }[]
    byLevel: { level: string; count: number; sum: number }[]
    notAssigned: { status: string; fund: string; kan: string; sum: number; basis: string }[]
    consolidationPairs: { from: string; to: string; eliminated: number; counterpart: number; ok: boolean; counterpartCount: number }[]
  }
  checks: Check[]
  notYetReconciled: typeof NOT_YET_RECONCILED
  customColumnTypes: typeof CUSTOM_COLUMN_TYPES
  portability: typeof PORTABILITY
  caveats: typeof CAVEATS
  yearSurvey: YearSurvey | null
  outputs: { path: string; description: string; bytes: number }[]
}

/** 1行が入力から出力へどう変わったかを、実物から組み立てる */
function walkthroughOf(table: CanonicalTable, source: BudgetSource): ReportData['walkthrough'] {
  const row = table.rows[0]!
  const levels = table.levels
  const fields: ReportData['walkthrough']['fields'] = [
    { column: 'budget_line_id', value: String(row.budget_line_id), origin: '団体コード・年度・direction・予算段階と、階層のセル全文から導出' },
    { column: 'fiscal_year', value: String(row.fiscal_year), origin: `原典に無い。${table.provenance.fiscalYearBasis}` },
    { column: 'direction', value: String(row.direction), origin: 'リソースごとの定数' },
    { column: 'phase_id', value: String(row.phase_id), origin: `取得元の設定（${source.phase.label}）` },
  ]
  for (const l of levels) {
    fields.push({
      column: `${l.key}_code / ${l.key}_label / ${l.key}_source`,
      value: `${row[`${l.key}_code`]} / ${row[`${l.key}_label`]} / ${row[`${l.key}_source`]}`,
      origin: `原典の「${l.sourceColumn}」1セルを3列へ分離（連結すると原文へ戻る）`,
    })
  }
  fields.push(
    { column: 'value', value: yen(Number(row.value)), origin: `原典の ${yen(Number(row.source_amount))}${source.amountUnit.label} を ×${source.amountUnit.multiplier} して円へ正規化` },
    { column: 'source_amount / source_amount_unit', value: `${yen(Number(row.source_amount))} / ${row.source_amount_unit}`, origin: '原典の値と単位をそのまま保持' },
    { column: 'source_row', value: String(row.source_row), origin: '原典の物理行番号' },
  )
  return { sourceLine: [...levels.map((l) => row[`${l.key}_source`]), row.source_amount].join(','), fields }
}

/** **集計はここだけ。** Markdown も画面もこの結果を読む */
export function buildReportData(args: {
  source: BudgetSource
  expenditure: CanonicalTable
  revenue: CanonicalTable
  derived: DerivedTable
  checks: Check[]
  outputs: { path: string; description: string; bytes: number }[]
  yearSurvey: YearSurvey | null
  /** どのノードがどのファイルとして配られるか。命名は呼び出し側が握る */
  artifactOf: (kind: NodeKind, direction: Direction) => string | undefined
}): ReportData {
  const { source, expenditure, revenue, derived, checks, outputs, yearSurvey, artifactOf } = args
  const tables = [expenditure, revenue]

  const byState = tally(derived.rows, (r) => [r.cofog_status, r.cofog_consolidation, r.cofog_division_code].join(SEP), (r) => Number(r.value))
  const byKan = tally(
    derived.rows,
    (r) => [r.fund_source, r.kan_source, r.cofog_division_code, r.cofog_status, r.cofog_decided_at_level, r.cofog_basis].join(SEP),
    (r) => Number(r.value),
  )
  const byLevel = tally(derived.rows, (r) => String(r.cofog_decided_at_level), (r) => Number(r.value))
  const notAssigned = tally(
    derived.rows.filter((r) => r.cofog_status !== 'assigned'),
    (r) => [r.cofog_status, r.fund_source, r.kan_source, r.cofog_basis].join(SEP),
    (r) => Number(r.value),
  )

  return {
    meta: {
      jurisdictionCode: source.jurisdictionCode,
      jurisdictionName: source.jurisdictionName,
      fiscalYear: source.fiscalYear,
      fiscalYearLabel: source.fiscalYearLabel,
      phase: source.phase,
      coverageNote: source.coverageNote,
      license: source.license,
      attribution: source.attribution,
      landingPage: source.landingPage,
      generatedAt: new Date().toISOString(),
    },
    summary: { total: checks.length, passed: checks.filter((c) => c.ok).length, failed: checks.filter((c) => !c.ok).length },
    topology: buildTopology({
      canonical: [expenditure, revenue],
      derived,
      derivedDirection: expenditure.direction,
      artifactOf,
    }),
    extract: tables.map((t) => t.provenance),
    load: tables.map((t) => ({
      direction: t.provenance.direction,
      inputRows: t.provenance.rows,
      outputRows: t.rows.length,
      diff: t.rows.length - t.provenance.rows,
      absentLevelCells: t.absentLevelCells,
      irregularCells: t.irregularCells.length,
    })),
    walkthrough: walkthroughOf(expenditure, source),
    levels: tables.map((t) => ({
      direction: t.provenance.direction,
      items: t.levels.map((l, i) => ({
        sourceColumn: l.sourceColumn,
        vocabulary: l.vocabulary === 'statutory' ? '地方自治法' : `${source.jurisdictionName}固有`,
        distinctCodes: new Set(t.rows.map((r) => String(r[`${l.key}_code`]))).size,
        distinctPaths: new Set(t.rows.map((r) => t.levels.slice(0, i + 1).map((p) => r[`${p.key}_source`]).join('/'))).size,
        columnType: l.codeType,
      })),
    })),
    transform: {
      cofogVersion: COFOG_VERSION,
      cofogSource: COFOG_SOURCE,
      ruleCount: RULE_IDS.length,
      inputRows: expenditure.rows.length,
      outputRows: derived.rows.length,
      consolidationScope: CONSOLIDATION_SCOPE,
      byState: [...byState.keys()].sort().map((k) => {
        const [status, consolidation, division] = k.split(SEP)
        return { status: status!, consolidation: consolidation!, division: division!, divisionLabel: division ? (COFOG_DIVISIONS[division] ?? '') : '', ...byState.get(k)! }
      }),
      byKan: [...byKan.keys()].sort().map((k) => {
        const [fund, kan, division, status, decidedAtLevel, basis] = k.split(SEP)
        return { fund: fund!, kan: kan!, division: division!, divisionLabel: division ? (COFOG_DIVISIONS[division] ?? '') : '', status: status!, decidedAtLevel: decidedAtLevel!, sum: byKan.get(k)!.sum, basis: basis! }
      }),
      byLevel: ['会計', '款', '項', '目', '節', '（規則なし）'].flatMap((k) => {
        const v = byLevel.get(k)
        return v ? [{ level: k, ...v }] : []
      }),
      notAssigned: [...notAssigned.keys()].sort().map((k) => {
        const [status, fund, kan, basis] = k.split(SEP)
        return { status: status!, fund: fund!, kan: kan!, sum: notAssigned.get(k)!.sum, basis: basis! }
      }),
      consolidationPairs: derived.consolidationPairs.map((p) => ({
        from: p.from,
        to: p.to,
        eliminated: p.eliminated,
        counterpart: p.counterpart,
        ok: p.eliminated === p.counterpart,
        counterpartCount: p.counterpartIds.length,
      })),
    },
    checks,
    notYetReconciled: NOT_YET_RECONCILED,
    customColumnTypes: CUSTOM_COLUMN_TYPES,
    portability: PORTABILITY,
    caveats: CAVEATS,
    yearSurvey,
    outputs,
  }
}

export type { Row }
