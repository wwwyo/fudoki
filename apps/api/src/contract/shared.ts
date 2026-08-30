/**
 * リソースをまたいで共有する contract の部品。
 * エラーの語彙とページングの入力はここで1回だけ定義し、各リソースが継承する。
 */
import { oc } from '@orpc/contract'
import * as z from 'zod'

/** AIP-122 のリソース名。例: jurisdictions/132195/budgetLines/132195:2018:... */
export const resourceName = z.string()

/**
 * 以下は fudoki（と団体の宣言）が定める閉じた語彙。enum にしてあるので、
 * 収録団体が増えて新しい値が現れると build の zod 検証が落ち、
 * ここへ足すまで deploy できない（黙って語彙が広がる事故を防ぐ）。
 */

/** 階層の名前。団体ごとに使う部分集合が違う（budgetLines の hierarchy に現れる並びが宣言） */
export const levelName = z
  .enum([
    'fund',
    'kan',
    'kou',
    'moku',
    'jikou',
    'daijigyo',
    'chujigyo',
    'shojigyo',
    'saimoku',
    'setsu',
    'saisetsu',
    'saisaisetsu',
  ])
  .describe(
    '階層の名前（fund=会計, kan=款, kou=項, moku=目, jikou=事項, daijigyo=大事業, chujigyo=中事業, shojigyo=小事業, saimoku=細目, setsu=節, saisetsu=細節, saisaisetsu=細々節）',
  )

/** 階層以外の同一性の軸の名前 */
export const dimensionName = z
  .enum(['org', 'budget_class'])
  .describe('軸の名前（org=所属（部課）, budget_class=予算区分（現年度・繰越明許・事故繰越））')

/** 予算段階の id。FDP の慣行 + fudoki が宣言した段階 */
export const phaseId = z
  .enum(['approved', 'adjusted', 'adjusted-before-transfer', 'executed'])
  .describe('予算段階（approved=当初予算, adjusted=予算現額, adjusted-before-transfer=補正後予算額（流用・充用前）, executed=執行済額）')
export type PhaseId = z.infer<typeof phaseId>

export const direction = z
  .enum(['expenditure', 'revenue'])
  .describe('歳出 / 歳入')

export const cofogStatus = z
  .enum(['assigned', 'unclassifiable', 'out-of-scope', 'not-applicable'])
  .describe('分類の状態（assigned=割当済み / unclassifiable=分類不能 / out-of-scope=対象外（公債費の元金償還など） / not-applicable=歳入なので対象外）')

export const cofogConsolidation = z
  .enum(['retained', 'eliminated'])
  .describe('連結状態（retained=保持 / eliminated=会計間移転として消去済み）。全会計を合計するとき eliminated を除くと二重計上を避けられる')

export const cofogDecidedAtLevel = z
  .enum(['会計', '款', '項', '目', '節', '（規則なし）'])
  .describe('どの階層の単位で分類が決まったか')

/** 全 procedure 共通のエラー語彙 */
export const base = oc.errors({
  BAD_REQUEST: {
    data: z
      .object({
        reason: z.string(),
        /**
         * 「次に何を指定すればよいか」を機械可読で示す（design doc「400 の本文には
         * 必ず code と、supportedGroupings や allowedValues のような次に何を指定すればよいかを入れる」）。
         * MCP は tool 実行エラーを言語モデルが自己修正するための応答と位置づけており、
         * message の自由文だけでは分岐できない。
         */
        supportedGroupings: z.array(z.array(z.string())).optional().describe('groupBy に指定できる組み合わせの一覧'),
        allowedValues: z.array(z.string()).optional().describe('phase / fund など、typed field に指定できる値の一覧'),
        /**
         * budgets:aggregate の direction 制約（PR #27 レビュー指摘）。歳入を拒否する理由が
         * 「COFOG が無いから」ではなく「歳入の集計自体を v1 でまだ実装していないから」であることを、
         * 400 の本文からも機械可読に示す。
         */
        supportedDirections: z.array(direction).optional().describe('typed field の direction に指定できる値の一覧'),
      })
      .optional(),
  },
  NOT_FOUND: {},
  /** deploy をまたいだ pageToken。入力誤り（400）と区別して 410 で返す */
  STALE_PAGE_TOKEN: {
    status: 410,
    message: 'pageToken was issued for a different revision. Restart from the first page.',
  },
})

/**
 * ページングの入力の部品。**メソッドごとに専用の入力定義を持つ**方針（design doc「条件は
 * typed field で受け、filter は範囲の絞り込みだけに使う」）なので、`filter` は各メソッドの
 * 説明文つきで個別に宣言し、ここでは pageSize / pageToken だけを共有部品として切り出す。
 */
export const pageSizeInput = z
  .coerce.number().int().min(0).optional()
  .describe('1ページの最大件数。未指定・0 は既定値 1000。上限 1000（超過は丸める）。負数は 400')

export const pageTokenInput = z
  .string()
  .optional()
  .describe('前ページの nextPageToken。発行時と同じ問い合わせでだけ使える（pageSize は変えてよい）。deploy をまたぐと 410')

/** AIP-158 のページング入力（List 系が spread して使う） */
export const pageInput = {
  filter: z
    .string()
    .optional()
    .describe(
      'AIP-160 の部分集合。`field = value` を AND でつなぐ形のみ。' +
        '使えるフィールドは fiscalYear / direction / phase / cofog.division（scope ごとの必須・可否はエンドポイントの説明を参照）',
    ),
  pageSize: pageSizeInput,
  pageToken: pageTokenInput,
}
