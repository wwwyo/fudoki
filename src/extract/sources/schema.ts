import { z } from 'zod'

/**
 * 会議録システムのベンダーファミリー。
 * driver は自治体単位ではなくここで切る（DiscussNetPremium 1本で全国約480自治体をカバーするため）。
 */
export const SystemFamily = z.enum([
  'dnp', // DiscussNetPremium（NTT-AT）— ssp.kaigiroku.net
  'db-search', // DB-Search（大和速記情報センター）— *.dbsr.jp
  'voices', // VOICES/Web — voices/*.asp
  'kensakusystem', // kensakusystem.jp
  'own-site', // 自治体独自（CMS / CGI / PDF 直置き）
  'none', // 会議録が Web 公開されていない
])

/** robots.txt が会議録の経路に対して何を許しているか */
export const RobotsVerdict = z.enum([
  'allowed', // 制限なし、または会議録の経路が Disallow 対象外
  'partial', // 一部パス／一部 User-agent のみ制限
  'disallow-all', // トップ以外を Disallow（DB-Search 型）
  'none', // robots.txt 自体が存在しない
  'unknown',
])

/** AI/LLM クローラ（GPTBot / ClaudeBot / CCBot 等）を名指しで拒否しているか */
export const AiCrawler = z.enum([
  'disallowed', // 明示的に拒否している
  'unspecified', // robots に AI 個別の指定がない
  'unchecked', // 未確認
])

/** 取得対象から外れている場合、その障害が解除しうる性質のものか */
export const BlockedBy = z.enum([
  'permission', // 許諾取得または追加調査で解除しうる
  'no-source', // 会議録が公開されていないため技術的に解除できない
])

export const FetchReason = z.enum([
  'robots-allowed',
  'tenant-render-only', // 取得可だが JSON API は Disallow のため画面を描画して解析する
  'robots-disallow-all',
  'ai-crawler-disallowed',
  'robots-unverified',
  'no-source',
])

export const Robots = z.object({
  verdict: RobotsVerdict,
  aiCrawler: AiCrawler,
  /** robots.txt の実文（要約している場合あり）。null は未取得 */
  raw: z.string().nullable(),
  source: z.string().optional(),
  host: z.string().optional(),
})

export const FetchPolicy = z.object({
  eligible: z.boolean(),
  reason: FetchReason,
  blockedBy: BlockedBy.nullable(),
  /** 許諾取得や追加調査で eligible に転じうるか */
  revisitable: z.boolean(),
  decidedAt: z.iso.date(),
})

export const Transcript = z.object({
  systemFamily: SystemFamily,
  transcriptUrl: z.url().nullable().optional(),
  robots: Robots,
  fetchPolicy: FetchPolicy,
  /** 委員会記録も収録しているか。予算の実質審議は委員会で行われるため重要 */
  hasCommittee: z.union([z.boolean(), z.literal('unknown')]).nullable().optional(),
  /** full = 全文記録（逐語）、summary = 要点記録 */
  recordType: z.enum(['full', 'summary', 'unknown']).nullable().optional(),
  confidence: z.enum(['confirmed', 'probable', 'unverified', 'failed']),
  verifiedAt: z.iso.date().optional(),
  evidenceUrls: z.array(z.url()).optional(),
  notes: z.string().optional(),
  /** DiscussNetPremium のテナント識別子 */
  tenant: z.string().optional(),
  tenantId: z.number().int().optional(),
  entryUrl: z.url().optional(),
  host: z.string().optional(),
})

/** 東京都オープンデータカタログ（CKAN）で見つかった1データセット */
export const OpenDataset = z.object({
  title: z.string(),
  formats: z.array(z.string()),
  url: z.string(),
  license: z.string().nullable(),
  /** 同カテゴリで見つかったデータセット数 */
  count: z.number().int().positive(),
})

/** 自治体が独自に持つポータル（東京都カタログとは別） */
export const OwnPortal = z.object({
  type: z.enum(['ckan', 'dcat', 'linkdata', 'html']),
  baseUrl: z.url(),
  feed: z.string().optional(),
  orgFilter: z.string().optional(),
  datasets: z.number().int().nullable(),
})

export const OpenData = z.object({
  tokyoCatalogDatasets: z.number().int().nonnegative(),
  budget: OpenDataset.nullable(),
  memberRoster: OpenDataset.nullable(),
  procurement: OpenDataset.nullable(),
  gikaiDayori: OpenDataset.nullable(),
  ownPortal: OwnPortal.optional(),
})

export const Status = z.object({
  driver: z.enum(['not-started', 'in-progress', 'implemented']),
  ingestValidated: z.boolean(),
  published: z.boolean(),
})

export const Jurisdiction = z.object({
  name: z.string(),
  /** Open Civic Data 形式の識別子。本家未登録の市区町村は同形式で自前定義 */
  ocdId: z.string().regex(/^ocd-division\/country:jp\/prefecture:\d{2}\/city:\d{6}$/),
  transcript: Transcript,
  openData: OpenData,
  status: Status,
})

export const Manifest = z.object({
  $schema: z.string().optional(),
  generatedAt: z.iso.date(),
  note: z.string(),
  sources: z.record(z.string(), z.url()),
  fetchPolicy: z.object({
    decidedAt: z.iso.date(),
    rule: z.string(),
    reasons: z.record(z.string(), z.string()),
    blockedBy: z.record(z.string(), z.string()),
  }),
  /** キーは全国地方公共団体コード（6桁） */
  jurisdictions: z.record(z.string().regex(/^\d{6}$/), Jurisdiction),
})

export type SystemFamily = z.infer<typeof SystemFamily>
export type RobotsVerdict = z.infer<typeof RobotsVerdict>
export type FetchReason = z.infer<typeof FetchReason>
export type Transcript = z.infer<typeof Transcript>
export type OpenData = z.infer<typeof OpenData>
export type Jurisdiction = z.infer<typeof Jurisdiction>
export type Manifest = z.infer<typeof Manifest>

/** driver が取得対象を選ぶときの唯一の入口 */
export function eligibleJurisdictions(m: Manifest): [string, Jurisdiction][] {
  return Object.entries(m.jurisdictions).filter(([, j]) => j.transcript.fetchPolicy.eligible)
}
