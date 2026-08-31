/**
 * budgets リソース（団体 × 年度の予算）。**root のコレクション**で、
 * 一覧の絞り込み（団体・年度）は filter で表現する。
 * budget は年度スコープのメタ（収録 direction、分類率、金額の段階）を持ち、
 * 明細（budgetLines）をサブリソースとして持つ。budgetLines は集約の内部なので
 * 独立したファイルにせず、このファイル（budget 集約）に同居させる。
 *
 * budget の id は `{団体コード}:{年度}`（例: 132195:2023）。
 * budget_line_id の先頭2セグメントと一致し、明細から親 budget が機械的に決まる。
 */
import * as z from 'zod'
import {
  base,
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogStatus,
  dimensionName,
  direction,
  levelName,
  pageInput,
  pageSizeInput,
  pageTokenInput,
  phaseId,
  resourceName,
} from './shared'

/**
 * budget id のコーデック。**形式（{6桁の団体コード}:{4桁の年度}）を知るのはここだけ**。
 * 作る側（build）は budgetIdOf、読む側（procedure）は parseBudgetId を使い、
 * 独立に文字列連結・正規表現を書かない。
 */
export const BUDGET_ID_PATTERN = /^(\d{6}):(\d{4})$/

export function budgetIdOf(jurisdiction: string, fiscalYear: string): string {
  const id = `${jurisdiction}:${fiscalYear}`
  if (!BUDGET_ID_PATTERN.test(id)) throw new Error(`malformed budget id would be produced: ${id}`)
  return id
}

/** 形式が違えば null（呼び出し側が 400 にする） */
export function parseBudgetId(id: string): { jurisdiction: string; fiscalYear: string } | null {
  const m = id.match(BUDGET_ID_PATTERN)
  if (!m) return null
  return { jurisdiction: m[1]!, fiscalYear: m[2]! }
}

/**
 * budgetLineId の先頭3セグメント（{団体}:{年度}:{direction}）を取り出す。
 * storedBudgetLineSchema の説明どおり「先頭2セグメントが親 budget の id」で、3番目が direction。
 * 名称索引（NameIndexRef）が jurisdiction・fiscalYear・direction を持たずに済むのはこの形式のおかげ
 * （budgetLineId 自体がそれらを機械的に決める）。形式が違えば null。
 */
export function parseBudgetLineId(id: string): { jurisdiction: string; fiscalYear: string; direction: 'expenditure' | 'revenue' } | null {
  const m = id.match(/^(\d{6}):(\d{4}):(expenditure|revenue):/)
  if (!m) return null
  return { jurisdiction: m[1]!, fiscalYear: m[2]!, direction: m[3] as 'expenditure' | 'revenue' }
}

// ---- scopes（direction ごとの収録範囲。design doc「収録範囲は direction ごとに返す」） ----

const lineAmountStat = z.object({
  lineCount: z.number().describe('明細数（一意な budget_line_id の件数）'),
  amount: z.number().describe('円に正規化した金額合計'),
})

const phaseScope = z.object({
  id: phaseId,
  label: z.string().describe('予算段階の原典での呼び名'),
  isPrimary: z.boolean().describe('build.ts の AMOUNT_PHASE（分類率・連結・cofogDepth の金額に使う段階）と一致するか'),
})

const fundScope = z.object({
  code: z.string().describe('会計コード。空文字はその団体がコード自体を持たないことを表す正当な値（例: 原典が会計名称しか持たない団体）'),
  label: z.string().nullable().describe('会計の名称。無ければ null'),
})

/**
 * この budget（団体×年度）の consolidation は isPrimary の段階の行だけを対象にする。
 * 段階ごとに連結の内訳が変わるわけではないが、対象を1段階に固定しないと
 * 複数段階ぶんの行を二重に数えてしまう（狛江市は歳出で3段階を持つ）。
 */
const consolidationScope = z.object({
  retained: lineAmountStat,
  eliminated: lineAmountStat,
})

/**
 * 歳入は COFOG が not-applicable なので `applicable: false` にし、率のフィールド自体を持たせない。
 * `rate: null` のような「常に存在するが空」の形にすると、歳入の分類漏れなのか
 * そもそも対象外なのかを呼び出し側が判別できない。
 */
const cofogDepthLevel = lineAmountStat.extend({
  rate: z.number().min(0).max(1).describe('割当済み（cofog_status=assigned）の行のうち、この深さまで降りている行の割合'),
})
const cofogDepthScope = z.discriminatedUnion('applicable', [
  z.object({
    applicable: z.literal(true),
    division: cofogDepthLevel,
    group: cofogDepthLevel,
    class: cofogDepthLevel,
  }),
  z.object({
    applicable: z.literal(false).describe('歳入は COFOG の対象外（cofog_status は常に not-applicable）'),
  }),
])

const hierarchyNameScope = z.object({
  level: levelName,
  hasName: z.boolean().describe('この年度・direction のどこかの行で、この階層の名称が得られているか（全行ではない。会計（fund）で割れる団体があるため）'),
  source: z
    .enum(['canonical', 'judgment'])
    .nullable()
    .describe('hasName が true のときの名称の出所。canonical=原典の列, judgment=fudoki の対応づけ（決算資料 PDF など）。false のときは null'),
})

/**
 * 事業名（大事業・細目・事項など、目より下の名称）の収録状況。
 * ⚠️ funds/fiscalYears はこの budget の年度に絞らず、団体×direction 全体で
 * 事業名が付いている範囲を返す（design doc の例が複数年度を1つの budget の
 * 応答内に列挙しており、単一年度に絞ると表現できないため）。
 */
const projectNameScope = z
  .object({
    hasName: z.literal(true),
    source: z.literal('judgment').describe('事業名は fudoki が決算資料等から対応づけた判断（原典にあるものは names.hierarchy 側で表す）'),
    funds: z.array(z.string()).describe('事業名が付く会計コード（団体×direction 全体）'),
    fiscalYears: z.array(z.string()).describe('事業名が付く年度（団体×direction 全体）'),
  })
  .nullable()

/**
 * 目の下に事業階層（大事業・細目・事項など）があるのに、集計の軸としては出していないことを示す。
 * design doc Caveats 2: 階層の集計は目までで、これは団体をまたぐ正規化の話ではなく
 * 「名称の欠損が多く、言語モデルがどのセルを選ぶべきか決められない」ことが理由。
 * ⚠️ available/aggregateSupported/alternative は今のところ常に固定値になる
 * （v1 では該当レベルがあれば必ず「未対応」なので）。将来 aggregateSupported が
 * true になる団体が出たときに初めて意味を持つ設計上の余地として残す。
 */
const nextHierarchyLevelScope = z
  .object({
    level: levelName,
    available: z.literal(true).describe('原典にこの階層のデータが実在する'),
    aggregateSupported: z.literal(false).describe('v1 の集計はこの階層を軸に出していない（design doc Caveats 2）'),
    namedAmountRate: z
      .number()
      .min(0)
      .max(1)
      .describe('団体×direction 全体で、この階層に名称が付いている金額の割合。金額は同じ scope の amountPhase で計算する'),
    alternative: z
      .literal('budgetLines:search')
      .describe('名称からの発見手段（design doc: 検索メソッド。本 API にはまだ実装されていない）'),
  })
  .nullable()

const budgetDirectionScope = z.object({
  // ⚠️ consolidation/cofogDepth/nextHierarchyLevel の金額はすべてこの段階で計算している。
  // phases[].isPrimary と同じ値になる（build.ts の検査が一致を見る）が、値を読むためだけに
  // phases 配列を線形探索させないよう、金額と同じ場所に条件そのものを置く
  // （design doc: 数値を返す応答から、その数値を計算した条件が分かるようにする）。
  amountPhase: phaseId.describe('この scope 内の金額（consolidation / cofogDepth / nextHierarchyLevel.namedAmountRate）を計算した予算段階。phases のうち isPrimary: true の phase と一致する'),
  phases: z.array(phaseScope).describe('この年度・direction が実在する予算段階（この budget の明細に現れる集合と一致）'),
  funds: z.array(fundScope).describe('この年度・direction に実在する会計（この budget の明細に現れる集合と一致）'),
  consolidation: consolidationScope,
  cofogDepth: cofogDepthScope,
  names: z.object({
    hierarchy: z.array(hierarchyNameScope).describe('款・項・目（集計が axis として出す階層）の名称の収録状況'),
    projectName: projectNameScope,
  }),
  nextHierarchyLevel: nextHierarchyLevelScope,
})
export type BudgetDirectionScope = z.infer<typeof budgetDirectionScope>

const budgetScopesSchema = z.object({
  expenditure: budgetDirectionScope.optional().describe('directions に expenditure を含まない年度は省略する'),
  revenue: budgetDirectionScope.optional().describe('directions に revenue を含まない年度は省略する'),
})
export type BudgetScopes = z.infer<typeof budgetScopesSchema>

export const budgetSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。budgets/{id}'),
  id: z
    .string()
    .regex(BUDGET_ID_PATTERN)
    .describe('budget の識別子。{団体コード}:{年度}（budget_line_id の先頭2セグメントと一致）'),
  jurisdictionId: z.string().describe('全国地方公共団体コード'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  directions: z.array(direction).describe('この予算で収録している歳出・歳入の別'),
  amountPhase: phaseId.describe('分類率の金額ベースの計算に使った予算段階'),
  classificationRate: z
    .object({
      assigned: z.object({
        lines: z.number().describe('明細数（一意な budget_line_id の件数）'),
        amount: z.number().describe('amountPhase 時点の金額合計（円）'),
      }),
      unclassifiable: z.object({
        lines: z.number().describe('明細数'),
        amount: z.number().describe('金額合計（円）'),
      }),
      outOfScope: z.object({
        lines: z.number().describe('明細数'),
        amount: z.number().describe('金額合計（円）'),
      }),
    })
    .describe('歳出の COFOG 分類の内訳。3状態の合計が歳出全体に一致する。COFOG で絞った結果に含まれない明細の規模がここで分かる'),
  scopes: budgetScopesSchema.describe('direction ごとの収録範囲（予算段階・会計・連結・COFOG の到達度・名称）'),
})
export type Budget = z.infer<typeof budgetSchema>

export const listBudgetsOutput = z.object({
  budgets: z.array(budgetSchema).describe('id の昇順'),
  revision: z.string().describe('由来する配布物の revision（git commit）'),
})

export const listBudgets = base
  .route({
    method: 'GET',
    path: '/budgets',
    summary: 'List budgets',
    description:
      '収録している予算（団体 × 年度）の一覧。これがカバレッジの正体で、' +
      'どの団体のどの年度が収録済みかは budgets の存在から導出する。' +
      'filter で `jurisdiction` と `fiscalYear` を絞れる（例: `jurisdiction = "132195"`）。' +
      '件数が少ないためページングは持たない。明細は /budgets/{id}/budgetLines から取得する。',
  })
  .input(
    z.object({
      filter: z
        .string()
        .optional()
        .describe('AIP-160 の部分集合（`=` と `AND`）。使えるフィールドは jurisdiction / fiscalYear'),
    }),
  )
  .output(listBudgetsOutput)

export const getBudget = base
  .route({
    method: 'GET',
    path: '/budgets/{budget}',
    summary: 'Get a budget',
  })
  .input(z.object({ budget: z.string().describe('budget の識別子（{団体コード}:{年度}）') }))
  .output(
    z.object({
      budget: budgetSchema,
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )

// ---- 明細の内部表現（配布物パーティションの保存形式。build.ts が書き、procedure が読む） ----
//
// ここの2つの schema（storedBudgetLineSchema / storedCrossBudgetLineSchema）は
// **配布物パーティション（lines/*.json・cofog/*.json）の保存形式**であって、
// API が返す公開スキーマではない（公開スキーマは budgetLineSchema。下の
// 「budgetLines（明細の一覧）」を参照）。両者を分けている理由は、
// 保存形式は build.ts が検算（多重集合一致など）するための完全な形を保つ必要がある一方、
// 公開スキーマは design doc「明細の一覧」が定める view（BASIC/FULL）で
// フィールドの充足度を変えるため、形が一致しないから。procedure がこの保存形式を
// view に応じて公開スキーマへ射影する。

const hierarchyEntry = z.object({
  level: levelName,
  code: z.string().describe('原典のコード。"0" はその階層を持たない行のプレースホルダ'),
  label: z.string().nullable().describe('原典の名称。名称の列を持たない団体（狛江市の款・項・目など）は null'),
})

const dimensionEntry = z.object({
  name: dimensionName,
  code: z.string().describe('原典のコード'),
  label: z.string().nullable().describe('原典の名称。無ければ null'),
})

const amountEntry = z.object({
  phase: phaseId,
  phaseLabel: z.string().describe('予算段階の原典での呼び名'),
  amount: z.number().describe('円に正規化した金額'),
  sourceAmount: z.number().describe('原典の額面（単位変換前の値）'),
  sourceAmountUnit: z.string().describe('原典の単位（円 / 千円）'),
  sourceRow: z.number().describe('原典 CSV での行番号。応答から原典の行へ戻るための参照'),
})

const cofogJudgment = z.object({
  status: cofogStatus,
  division: z.string().nullable().describe('COFOG の大分類コード（01〜10）。割当済み以外は null'),
  consolidation: cofogConsolidation,
  decidedAtLevel: cofogDecidedAtLevel.nullable(),
  ruleId: z.string().nullable().describe('適用した分類規則の id。配布物の cofog_rules リソースで根拠を引ける'),
})

export const storedBudgetLineSchema = z.object({
  budgetLineId: z.string().describe('配布物の明細識別子。{団体}:{年度}:{direction}:{資料種別}:{ハッシュ} の形で安定。先頭2セグメントが親 budget の id'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  direction,
  hierarchy: z.array(hierarchyEntry).describe('科目の階層（款→項→目→…）。並びと段数は団体ごとに違い、配列の並び順が上位から下位への順序'),
  dimensions: z.array(dimensionEntry).describe('階層以外の同一性の軸（狛江市の所属・予算区分）。無い団体は空配列'),
  amounts: z.array(amountEntry).describe('この明細が持つ予算段階ごとの金額。決算資料の明細は複数段階を持つ'),
  judgments: z
    .object({
      cofog: cofogJudgment.nullable().describe('COFOG 分類の判断。歳入は not-applicable'),
      projectName: z.string().nullable().describe('事業名。原典に無い場合に決算資料から fudoki が対応づけたもの（付かない明細は null）'),
    })
    .describe('fudoki の判断。上の正本由来フィールドと違い、自治体が公表した事実ではない'),
})
export type StoredBudgetLine = z.infer<typeof storedBudgetLineSchema>

export const storedCrossBudgetLineSchema = z.object({
  budget: z.string().describe('親 budget のリソース名（budgets/{団体コード}:{年度}）'),
  budgetLineId: z.string().describe('配布物の明細識別子'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  amounts: z
    .array(z.object({
      phase: phaseId,
      amount: z.number().describe('円に正規化した金額'),
    }))
    .describe('予算段階ごとの金額。段階の構成は団体で違うので、比較は同じ段階どうしで行うこと'),
  // 団体単位の行の cofogJudgment から共通の最小軸ぶんだけ導出する（二重定義しない）
  cofog: cofogJudgment
    .pick({ status: true, division: true, consolidation: true })
    .describe('COFOG 分類（fudoki の判断）'),
})
export type StoredCrossBudgetLine = z.infer<typeof storedCrossBudgetLineSchema>

// ---- budgetLines（明細の一覧。design doc「明細の一覧」） ----
//
// 判別可能な union（旧: scope: 'budget' | 'crossBudget'）をやめ、view にする。
// Why not a union: budget を親にした行も `-` で横断した行も、同じ BudgetLine という
// 1つのリソースの「フィールドの充足度」が違うだけで、別のリソースではない。
// union だと利用者から見て2種類のリソースがあるように見える。
// FULL を許すかどうかの制約も filter の中身ではなく path（親が実在するか `-` か）だけで決める。

/** view=BASIC でも返る、団体をまたいでも意味が揃う COFOG の最小項目 */
const commonCofog = cofogJudgment
  .pick({ status: true, division: true, consolidation: true })
  .nullable()
  .describe('COFOG 分類の共通項目（fudoki の判断）。歳入は not-applicable につき null。すべての view で返る')

const basicAmount = z.object({
  phase: phaseId.describe('isPrimary の段階（親 budget の scopes[direction].phases の isPrimary と一致）'),
  amount: z.number().describe('円に正規化した金額'),
})

export const budgetLineSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。budgets/{budget}/budgetLines/{budgetLineId} の形。すべての view で返る'),
  budgetLineId: z.string().describe('配布物の明細識別子。すべての view で返る'),
  budget: z.string().describe('親 budget のリソース名（budgets/{団体コード}:{年度}）。すべての view で返る'),
  fiscalYear: z.string().describe('会計年度（西暦）。すべての view で返る'),
  direction,
  amount: basicAmount.describe('view=BASIC の金額。段階を1つ（isPrimary）に絞った軽量な形。すべての view で返る'),
  cofog: commonCofog,
  hierarchy: z
    .array(hierarchyEntry)
    .optional()
    .describe('view=FULL でのみ返る。科目の階層（款→項→目→…）。団体固有の形なので、親が実在する budget のときだけ意味を持つ'),
  dimensions: z
    .array(dimensionEntry)
    .optional()
    .describe('view=FULL でのみ返る。階層以外の同一性の軸（狛江市の所属・予算区分）'),
  amounts: z
    .array(amountEntry)
    .optional()
    .describe('view=FULL でのみ返る。全段階の金額（原典の額面・単位・行番号つき）'),
  judgments: z
    .object({
      cofog: cofogJudgment.nullable().describe('COFOG 分類のフル判断。歳入は not-applicable'),
      projectName: z.string().nullable().describe('事業名。原典に無い場合に決算資料から fudoki が対応づけたもの（付かない明細は null）'),
    })
    .optional()
    .describe('view=FULL でのみ返る。fudoki の判断（上の commonCofog より詳しい根拠を含む）'),
})
export type BudgetLine = z.infer<typeof budgetLineSchema>

export const budgetLinesViewEnum = z
  .enum(['BASIC', 'FULL'])
  .describe(
    'BASIC（既定）=name・budget・direction・金額・共通の COFOG 項目だけの軽量な形。' +
      'FULL=BASIC に加えて hierarchy・dimensions・全段階の amounts・judgments を返す。' +
      '実在する budget を親にしたときだけ指定できる（横断のワイルドカード `-` では 400）',
  )
export type BudgetLinesView = z.infer<typeof budgetLinesViewEnum>

export const getBudgetLinesOutput = z.object({
  lines: z.array(budgetLineSchema).describe('budgetLineId の昇順'),
  nextPageToken: z.string().optional().describe('続きがあるときだけ返る。無ければ最後まで返した'),
  revision: z.string().describe('由来する配布物の revision（git commit）'),
})
export type GetBudgetLinesOutput = z.infer<typeof getBudgetLinesOutput>

export const getBudgetLinesInput = z.object({
  budget: z.string().describe('budget の識別子（{団体コード}:{年度}）、または全予算横断の `-`'),
  view: budgetLinesViewEnum.default('BASIC'),
  ...pageInput,
})

export const getBudgetLines = base
  .route({
    method: 'GET',
    path: '/budgets/{budget}/budgetLines',
    summary: 'List budget lines',
    description:
      '予算の明細。`{budget}` に budget の id（{団体コード}:{年度}）を指定すると、その予算の明細行を返す。' +
      'filter には direction が必須で、phase / cofog.division を追加できる。\n\n' +
      '`{budget}` にワイルドカード `-` を指定すると全予算を横断する（AIP-159）。' +
      'filter には cofog.division が必須で、fiscalYear を追加できる（direction / phase は使えない）。' +
      '各行の budget フィールドから親予算へ辿れる。\n\n' +
      '`view` で応答の充足度を選ぶ（既定 BASIC）。BASIC は name・budget・direction・金額（1段階）・' +
      '共通の COFOG 項目だけの軽量な形、FULL は団体固有の階層（hierarchy）・階層以外の軸（dimensions）・' +
      '全段階の金額（amounts）・fudoki の判断の全体（judgments）を追加する。' +
      'FULL は実在する budget を親にしたときだけ指定できる ── 団体固有の階層は団体を固定しないと意味を持たないため、' +
      '`-` に対して view=FULL を指定すると 400 になる。\n\n' +
      'filter の文法は AIP-160 の部分集合（`=` と `AND` のみ）。' +
      '例: `cofog.division = "09" AND fiscalYear = 2023`。' +
      'phase は amounts[].phase に対する仮想フィールド（いずれかの段階が一致したら真）で、' +
      '一致した行の amount / amounts は絞り込まれない（全段階のまま返る）。\n\n' +
      '並び順は budgetLineId の昇順。結果が複数ページに分かれる場合は nextPageToken が返り、' +
      'nextPageToken が無いことが「最後まで返した」ことを意味する。' +
      'フィルタの該当が薄いページは pageSize 未満の件数（0件を含む）になり得るが、' +
      'nextPageToken がある限り続きがある。',
  })
  .input(getBudgetLinesInput)
  .output(getBudgetLinesOutput)

// ---- aggregate（budgets コレクションのカスタムメソッド。design doc「引ける集計の一覧」） ----

/**
 * 集計の軸の名前。design doc Tasks 4 で COFOG、Tasks 5 で hierarchy、
 * Tasks 6 で fiscalYear を足した（すべて enum への追加だけで済んでいる）。
 */
export const groupingKey = z
  .enum(['jurisdiction', 'cofog.division', 'cofog.group', 'cofog.class', 'hierarchy', 'fiscalYear'])
  .describe(
    '集計の軸の名前。jurisdiction=団体, cofog.*=COFOG のディビジョン/グループ/クラス, ' +
      'hierarchy=科目階層（款・項・目。hierarchyParent で親を指定）, fiscalYear=年度横断（同一団体内）',
  )
export type GroupingKey = z.infer<typeof groupingKey>

/** filter が団体を1つに絞っている（jurisdiction + fiscalYear）ときに引ける groupBy */
export const SINGLE_BUDGET_GROUPINGS = [
  ['cofog.division'],
  ['cofog.group'],
  ['cofog.class'],
  ['hierarchy'],
  ['hierarchy', 'cofog.division'],
] as const satisfies readonly (readonly GroupingKey[])[]

/**
 * filter が団体を絞らない（fiscalYear だけの）ときに引ける groupBy。
 * `jurisdiction` を軸に含めることを必須にする ── これが「団体をまたいで足さない」を構造で守る仕組み
 * （design doc「団体をまたいだ合算をどう防ぐか」）。
 */
export const CROSS_JURISDICTION_GROUPINGS = [
  ['jurisdiction', 'cofog.division'],
  ['jurisdiction', 'cofog.group'],
  ['jurisdiction', 'cofog.class'],
] as const satisfies readonly (readonly GroupingKey[])[]

/**
 * filter が年度を絞らない（jurisdiction だけの）ときに引ける groupBy（design doc Tasks 6）。
 * `jurisdiction,fiscalYear` の組み合わせは v1 の allowlist に入れない（design doc Caveats 4:
 * 会計範囲が年度で変わる団体があり、並べるだけでは比較にならないため）。
 */
export const JURISDICTION_YEARS_GROUPINGS = [
  ['fiscalYear'],
  ['fiscalYear', 'cofog.division'],
] as const satisfies readonly (readonly GroupingKey[])[]

/**
 * 契約と前計算アセットを一対一にする allowlist（design doc「上限値ではなく allowlist を公開する」）。
 * 応答とエラーの両方の `supportedGroupings` はここから作る。3軸を足すときはここへの追加だけで済む。
 */
export const SUPPORTED_GROUPINGS: readonly (readonly GroupingKey[])[] = [
  ...SINGLE_BUDGET_GROUPINGS,
  ...CROSS_JURISDICTION_GROUPINGS,
  ...JURISDICTION_YEARS_GROUPINGS,
]

/**
 * budgets:aggregate が v1 で対応する direction。歳入を弾く理由は「歳入の集計自体を
 * 実装していない」であって、COFOG が歳入に無いことではない（歳入でも hierarchy や
 * fiscalYear の軸は意味を持つ。design doc は COFOG 軸だけを歳入の対象外にしている）。
 * ⚠️ 以前はエラーメッセージが COFOG を理由に挙げており、歳入の集計が設計より広く拒否されている
 * ように読めた（PR #27 レビュー指摘）。応答からもこの制約が分かるよう、成功応答・エラー応答の
 * 両方にこの一覧をそのまま載せる。
 */
export const SUPPORTED_AGGREGATE_DIRECTIONS: readonly z.infer<typeof direction>[] = ['expenditure']

/** groupBy の cofog.* 要素から前計算アセットの depth を導く（groupBy に cofog.* は高々1つ） */
export function cofogDepthOf(groupBy: readonly GroupingKey[]): 'division' | 'group' | 'class' {
  const g = groupBy.find((k) => k !== 'jurisdiction')
  if (g === 'cofog.division') return 'division'
  if (g === 'cofog.group') return 'group'
  if (g === 'cofog.class') return 'class'
  throw new Error(`groupBy has no cofog axis: ${groupBy.join(',')}`)
}

// ---- hierarchy 軸（design doc Tasks 5）。hierarchyParent の文法と、根/款/項からの子レベル導出 ----

export type HierarchyParentSegment = { level: 'kan' | 'kou'; code: string }

/**
 * `kan=10` / `kan=10/kou=04` の形の hierarchyParent を解く。
 * ⚠️ 目（moku）以下を親に指定させない ── design doc Caveats 2: 目より下は事業階層で、
 * 名称の欠損が多く言語モデルがセルを選べない。そのため許すのは根・款・項の3つだけで、
 * 3セグメント目や kan/kou 以外の level 名はすべて 400 の理由になる。
 */
export function parseHierarchyParent(raw: string): HierarchyParentSegment[] | { error: string } {
  if (raw.trim() === '') return { error: 'hierarchyParent must not be empty (omit the field for the root)' }
  const rawSegments = raw.split('/')
  if (rawSegments.length > 2) {
    return {
      error:
        `hierarchyParent has more than 2 segments: "${raw}". Only root, kan, and kan/kou are supported ── ` +
        'a 3rd segment would target moku (the project hierarchy), which is not an aggregation axis',
    }
  }
  const expectedLevels: readonly ('kan' | 'kou')[] = ['kan', 'kou']
  const out: HierarchyParentSegment[] = []
  for (let i = 0; i < rawSegments.length; i++) {
    const seg = rawSegments[i]!
    const eq = seg.indexOf('=')
    if (eq === -1) return { error: `malformed hierarchyParent segment (expected "level=code"): "${seg}"` }
    const level = seg.slice(0, eq)
    const code = seg.slice(eq + 1)
    if (code === '') return { error: `hierarchyParent segment has an empty code: "${seg}"` }
    const expected = expectedLevels[i]!
    if (level !== expected) {
      return {
        error:
          `hierarchyParent segment ${i} must be "${expected}" (got "${level}"). Only root, kan, and kan/kou ` +
          'are supported as hierarchyParent — moku and below return the project hierarchy, which this axis does not cover',
      }
    }
    out.push({ level: expected, code })
  }
  return out
}

/** hierarchyParent の直下1段（design doc「hierarchy の hierarchyParent は直下1段だけを返す」） */
export function hierarchyChildLevel(segments: readonly HierarchyParentSegment[]): 'kan' | 'kou' | 'moku' {
  if (segments.length === 0) return 'kan'
  if (segments.length === 1) return 'kou'
  return 'moku'
}

/** hierarchyParent の正規化文字列。前計算アセットのパス（`hierarchy/{親のパス}.json`）とファイル名を共有する */
export function hierarchyParentPathString(segments: readonly HierarchyParentSegment[]): string {
  return segments.length === 0 ? 'root' : segments.map((s) => `${s.level}=${s.code}`).join('/')
}

const aggStat = z.object({
  amount: z.number().describe('円に正規化した金額合計'),
  lineCount: z.number().describe('明細数（一意な budget_line_id の件数）'),
})

const aggregationDimension = z.object({
  dimension: groupingKey,
  code: z.string(),
  label: z.string().nullable(),
})

const aggregationCell = z.object({
  dimensions: z.array(aggregationDimension).min(1).describe('groupBy と同じ順序の値'),
  amount: z.number().describe('円に正規化した金額合計'),
  lineCount: z.number().describe('明細数'),
  fundScope: z
    .lazy(() => aggregateQueryFundScope)
    .optional()
    .describe(
      'groupBy が fiscalYear を含むときだけ持つ。狛江市の公共下水道特別会計が2020年度から原典に現れないように、' +
        '会計範囲は年度で変わりうるため、セルごとに持たせる（design doc「年度を軸にしたときは、セルごとに fundScope を持たせる」）',
    ),
})

const aggregationResidual = z.object({
  unclassifiable: aggStat.describe('cofog_status = unclassifiable の合計（cells には現れない）'),
  outOfScope: aggStat.describe('cofog_status = out-of-scope の合計（公債費の元金償還など。cells には現れない）'),
  notDescended: aggStat.describe('割当済み（assigned）だが groupBy が要求する深さのコードを持たない行の合計（例: division までしか降りていない行を group で集計したとき）'),
})

export const aggregateWarningCode = z.enum(['UNCONSOLIDATED_INTERFUND_TRANSFERS'])
export const aggregateOmittedCode = z.enum([
  'PHASE_NOT_AVAILABLE',
  /** fiscalYear 軸で fund を特定の会計コードに絞ったとき、その会計が無い年度（design doc Tasks 6） */
  'FUND_NOT_AVAILABLE',
])
/** この応答に現れうる判断の種類。cofog=集計、projectName=名称の検索（design doc「名称の検索」） */
export const judgmentKind = z.enum(['cofog', 'projectName'])

const aggregateQueryFundScope = z.object({
  funds: z.array(fundScope).describe('この応答が合算した会計'),
  consolidation: consolidationScope.describe(
    '連結の内訳（retained / eliminated）。fund = all で eliminated が非0のとき、全会計の合計は会計間の移転を二重に含む（warnings に UNCONSOLIDATED_INTERFUND_TRANSFERS が立つ）',
  ),
})

const aggregateQuery = z.object({
  filter: z.string().describe('受け取った filter のエコー（未指定なら空文字）'),
  direction,
  phase: z.object({ id: phaseId, label: z.string().describe('予算段階の原典での呼び名') }),
  fund: z.string().describe('会計コード。既定は "all"'),
  groupBy: z.array(groupingKey),
  hierarchyParent: z
    .string()
    .nullable()
    .describe('受け取った hierarchyParent のエコー。groupBy が hierarchy を含まない、または省略されたときは null'),
  budgets: z.array(z.string()).describe('この集計に含めた budget のリソース名（id 昇順）'),
  fundScope: aggregateQueryFundScope,
})

const provenanceSource = z.object({
  id: z.string(),
  title: z.string(),
  path: z.string().nullable(),
  license: z.string().describe('SPDX 形式のライセンス名。判断（judgment）由来で確定していないものは NOASSERTION'),
  kind: z.enum(['canonical', 'judgment']),
})

const aggregateProvenance = z.object({
  sources: z.array(provenanceSource).describe('実体は1回だけ置く。予算ごとの対応は byBudget が id で指す'),
  byBudget: z.record(z.string(), z.array(z.string())).describe('budget のリソース名 → 対応する sources[].id'),
  attribution: z.string().describe('そのまま表示できる帰属文'),
  modifications: z.string().describe('fudoki が行った改変の説明'),
})

export const aggregateBudgetsOutput = z.object({
  cells: z.array(aggregationCell),
  // ⚠️ 元は必須の単一オブジェクトだったが、団体横断（groupBy に jurisdiction を含む）応答では
  // 「全団体で1つに合算した residual」は total と同じ理由で存在しない（design doc「団体をまたいで
  // 足さない」）。合算した 0 を置く代わりに、団体が1つに閉じているときだけ residual を返し、
  // 団体をまたぐときは residualByJurisdiction を返す（PR #27 レビュー指摘）。
  residual: aggregationResidual.optional().describe('filter が単一の団体に閉じているときだけ返す。団体をまたぐときは residualByJurisdiction を見る'),
  residualByJurisdiction: z
    .record(z.string(), aggregationResidual)
    .optional()
    .describe('groupBy が jurisdiction を含むときだけ返す。団体コード → その団体の residual。団体ごとに cells + residualByJurisdiction[jurisdiction] を復元できる'),
  total: aggStat.optional().describe('filter が単一の団体に閉じているときだけ返す。複数団体にまたがるときは持たせない（0 も置かない）'),
  currency: z.literal('JPY'),
  amountUnit: z.literal('1').describe('cells / residual / total の金額は常に円（1倍）に正規化済み'),
  query: aggregateQuery,
  warnings: z.array(z.object({ code: aggregateWarningCode, message: z.string() })),
  omitted: z.array(z.object({ budget: z.string(), code: aggregateOmittedCode })).describe('条件（direction の phase など）を満たさず集計から除外した budget。黙って落とさない'),
  supportedGroupings: z.array(z.array(groupingKey)).describe('この filter の範囲で引ける groupBy の一覧'),
  // ⚠️ supportedGroupings だけでは「歳入は集計自体を実装していない」という direction の制約が
  // 応答から読み取れない（PR #27 レビュー指摘）。歳出の応答にも常に含め、歳入で 400 になったときの
  // エラー応答にも同じ一覧を載せる（procedure/budgets.ts）ことで、成功・失敗どちらの経路でも分かるようにする。
  supportedDirections: z.array(direction).describe('budgets:aggregate が現在対応する direction の一覧。歳入はここに無ければ集計自体が未対応（COFOG の欠如とは別の理由）'),
  judgment: z.array(judgmentKind).describe('この応答に含まれる fudoki の判断の種類'),
  provenance: aggregateProvenance,
  revision: z.string().describe('由来する配布物の revision（git commit）'),
  nextPageToken: z.string().optional().describe('続きがあるときだけ返る'),
})
export type AggregateBudgetsOutput = z.infer<typeof aggregateBudgetsOutput>

export const aggregateBudgetsInput = z.object({
  filter: z
    .string()
    .optional()
    .describe(
      'AIP-160 の部分集合（`=` と `AND`）。使えるフィールドは jurisdiction / fiscalYear のみ。' +
        '例: `jurisdiction = "132195" AND fiscalYear = 2023`（単一予算）、' +
        '`jurisdiction = "132195"`（fiscalYear 軸。同一団体の年度横断）、' +
        '`fiscalYear = 2023`（jurisdiction 軸。団体横断）。direction・phase・fund は typed field で指定する',
    ),
  direction,
  phase: phaseId,
  fund: z
    .string()
    .default('all')
    .describe(
      '会計コード。既定は "all"（全会計を合算）。特定の会計を指定するには filter で団体を1つに絞ること' +
        '（会計コードは団体で揃わない。例: 一般会計は三鷹市 "01" / 狛江市 "1" / 多摩市 ""）。' +
        'groupBy が hierarchy を含むときは "all" を指定できない（款・項のコードは会計内でしか一意でないため）',
    ),
  groupBy: z
    .array(groupingKey)
    .min(1)
    .max(2)
    .describe('集計の軸。引ける組み合わせは応答の supportedGroupings と同じ allowlist'),
  hierarchyParent: z
    .string()
    .optional()
    .describe(
      'groupBy が hierarchy を含むときだけ使える。直下1段だけを返す親の指定で、' +
        '形式は `kan=10` または `kan=10/kou=04`。省略すると根（款）を返す。' +
        '指定できるのは根・款・項までで、目（moku）以下を指定すると400（事業階層は集計の軸にしていない）',
    ),
  pageSize: pageSizeInput,
  pageToken: pageTokenInput,
})

export const aggregateBudgets = base
  .route({
    method: 'GET',
    path: '/budgets:aggregate',
    summary: 'Aggregate budgets by COFOG, hierarchy, or fiscal year',
    description:
      '団体・年度で絞った予算を COFOG（大分類・中分類・小分類）別・科目階層別に集計し、' +
      '同一団体の年度を横断できる（AIP-136 のコレクションカスタムメソッド）。' +
      '前計算済みの組み合わせだけを引ける（応答の supportedGroupings）。\n\n' +
      'filter が jurisdiction と fiscalYear の両方を指定したとき、その1つの budget を ' +
      '`groupBy = cofog.division`（または `.group` / `.class`）、`hierarchy`（hierarchyParent で親を指定）、' +
      'または `hierarchy,cofog.division` で集計する。\n\n' +
      'filter が jurisdiction だけのときは同一団体の年度を横断し、`groupBy = fiscalYear`（または ' +
      '`fiscalYear,cofog.division`）で集計する。会計範囲が年度で変わりうるため、セルごとに fundScope を持つ。\n\n' +
      'filter が fiscalYear だけのときは該当する全団体を横断し、groupBy に jurisdiction を含めることが必須になる' +
      '（含めないと、団体をまたいだ合計という存在しない数値を返すことになるため 400）。このとき fund は指定できない' +
      '（会計コードが団体で揃わないため）。\n\n' +
      'direction と phase は必須。歳出の複数の予算段階を区別せず合計する誤りを防ぐため、既定値は持たない。' +
      '⚠️ v1 では歳出（expenditure）のみ対応。歳入を指定すると 400（COFOG が歳入に無いからではなく、' +
      '歳入の集計自体を v1 でまだ実装していないため。hierarchy・fiscalYear の軸は歳入でも意味を持つ）。' +
      '応答・エラー応答の supportedDirections が、その時点で対応する direction を示す。',
  })
  .input(aggregateBudgetsInput)
  .output(aggregateBudgetsOutput)

// ---- budgetLines:search（budgets コレクションのカスタムメソッド。design doc「名称の検索」） ----

/**
 * 検索対象の名称フィールド。design doc「検索対象を2種類に分ける」:
 * accountLabel=原典の階層の名称（nameSource: canonical）、
 * projectName=project_names.csv による fudoki の対応づけ（nameSource: judgment）。
 */
export const nameFieldEnum = z
  .enum(['accountLabel', 'projectName'])
  .describe('accountLabel=原典の階層の名称（canonical）, projectName=fudoki が対応づけた事業名（judgment）')
export type NameFieldValue = z.infer<typeof nameFieldEnum>

const searchMatchedSchema = z.object({
  field: nameFieldEnum,
  level: levelName.describe('マッチした階層。projectName は常に daijigyo'),
  value: z.string().describe('マッチした名称そのもの（原典または fudoki の対応づけ）'),
})

export const searchMatchSchema = z.object({
  name: resourceName.describe('budgets/{budget}/budgetLines/{budgetLineId} の形'),
  budget: z.string().describe('親 budget のリソース名'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  direction,
  fund: fundScope,
  matched: searchMatchedSchema,
  nameSource: z.enum(['canonical', 'judgment']).describe('matched.value の出所'),
  hierarchy: z.array(hierarchyEntry).describe('この明細の科目階層（款→項→目→…）'),
  amounts: z
    .array(z.object({ phase: phaseId, amount: z.number().describe('円に正規化した金額') }))
    .describe('typed field の phase を指定したときはその段階だけに絞る。指定しなければ全段階'),
})
export type SearchMatch = z.infer<typeof searchMatchSchema>

/**
 * 名称の被覆状況が完全でない (budget, field) の組だけを列挙する
 * （design doc「coverage は固定値にせず、filter で絞られた範囲について計算する」）。
 * NO_NAMES=その (budget, direction) にこのフィールドの名称が一切無い、
 * PARTIAL_NAMES=一部の会計・年度・階層にしか無い。
 */
export const namedCoverageCode = z.enum(['NO_NAMES', 'PARTIAL_NAMES'])

const namedCoverageEntry = z.object({
  budget: z.string(),
  field: nameFieldEnum,
  funds: z.array(fundScope).describe('この名称が実際に付いている会計（NO_NAMES のときは参考として scope の全会計）'),
  code: namedCoverageCode,
  message: z.string(),
})

export const searchBudgetLinesOutput = z.object({
  matches: z.array(searchMatchSchema).describe('budgetLineId の昇順'),
  coverage: z.object({
    searchedNameFields: z.array(nameFieldEnum).describe('実際に検索対象にしたフィールド'),
    namedCoverage: z.array(namedCoverageEntry),
  }),
  judgment: z.array(judgmentKind).describe('この応答に含まれる fudoki の判断の種類'),
  provenance: aggregateProvenance,
  revision: z.string().describe('由来する配布物の revision（git commit）'),
  nextPageToken: z.string().optional().describe('続きがあるときだけ返る'),
})
export type SearchBudgetLinesOutput = z.infer<typeof searchBudgetLinesOutput>

export const searchBudgetLinesInput = z.object({
  query: z.string().min(1).describe('名称に対する部分一致の検索文字列（大文字小文字を区別する）'),
  filter: z
    .string()
    .optional()
    .describe('AIP-160 の部分集合（`=` と `AND`）。使えるフィールドは jurisdiction / fiscalYear のみ'),
  direction: direction.optional().describe('集計と違い任意。省略すると歳出・歳入の両方を検索する'),
  phase: phaseId.optional().describe('指定すると、この段階の金額を持つ明細だけに絞り、amounts もこの段階だけを返す'),
  fund: z
    .string()
    .optional()
    .describe('会計コード。指定するには filter に jurisdiction が必須（会計コードは団体で揃わないため）'),
  nameField: z
    .array(nameFieldEnum)
    .min(1)
    .optional()
    .describe('検索対象の名称フィールド。省略すると accountLabel と projectName の両方を検索する'),
  level: levelName.optional().describe(
    'accountLabel の検索をこの階層に絞る。原典がこの階層の名称を一切持たない場合（例: 狛江市の款・項・目）は' +
      '0件ではなく400を返す',
  ),
  pageSize: pageSizeInput,
  pageToken: pageTokenInput,
})

export const searchBudgetLines = base
  .route({
    method: 'GET',
    path: '/budgets/-/budgetLines:search',
    summary: 'Search budget lines by name',
    description:
      '名称（原典の科目階層名 accountLabel、または fudoki が対応づけた事業名 projectName）の部分一致で明細を横断検索する' +
      '（AIP-136 のコレクションカスタムメソッド）。三鷹市の「いじめ問題対策協議会関係費」は原典の事項の名称（jikou）にあり、' +
      '狛江市の「いじめ問題等対策推進」は project_names.csv による判断（daijigyo）にある。' +
      '出所が違うため、応答の各 match は nameSource（canonical / judgment）で区別する。\n\n' +
      'direction と phase は集計と違い任意（名称を引く段階では条件が定まっていないのが普通）。' +
      '返す match ごとに fiscalYear / direction / fund を明示する。\n\n' +
      'fund を指定するには filter に jurisdiction が必須（会計コードは団体で揃わない）。\n\n' +
      '応答の coverage は filter で絞られた範囲について計算し、名称が完全でない (budget, field) の組だけを列挙する。' +
      '0件が「該当なし」なのか「そもそも名称が付いていない」なのかは、これで区別する。\n\n' +
      '原典が名称を持たない階層（例: 狛江市の款・項・目）を level に指定すると、0件ではなく400を返し、' +
      'projectName で引けるかどうかを本文で示す。\n\n' +
      '並び順は明細識別子（budgetLineId）の昇順に固定。',
  })
  .input(searchBudgetLinesInput)
  .output(searchBudgetLinesOutput)
