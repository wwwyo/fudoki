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

/**
 * AI/LLM クローラを「意図して」拒否しているか。
 *
 * 線引きは意図の明確さで行う。`# --- AI・LLM ---` のようにセクションを切って
 * GPTBot / ClaudeBot / anthropic-ai / Google-Extended を列挙しているものは `disallowed`。
 *
 * ⚠️ CCBot（Common Crawl）は判断が割れる。本来は汎用の web アーカイブクローラだが、
 * そのアーカイブが LLM の主要な学習データ源であるため、AI 対策として弾かれることもある。
 * ただし DotBot / SemrushBot / AhrefsBot / MJ12bot と並ぶ「迷惑ボット対策の定型
 * ブロックリスト」の中にある場合は AI 意図と断定できないため `unspecified` とする。
 *
 * なお **この値は取得可否の直接の根拠ではない**。robots.txt の仕様上、UA 指定の
 * ルールはその UA にしか適用されず、fudoki に効くのは `User-agent: *` グループだけ。
 * この値は「相手が AI にどういう姿勢か」を記録するためのもので、判断は意図が
 * 明確な場合にのみ尊重する。
 */
export const AiCrawler = z.enum([
  'disallowed', // AI/LLM を意図して拒否している
  'unspecified', // AI 個別の指定がない（汎用ブロックリストに CCBot 等がある場合を含む）
  'unchecked', // 未確認
])

/** 取得・再配布それぞれの判断 */
export const Decision = z.enum([
  'allow', // 判断が済んでいて実行してよい
  'deny', // 構造的に不可、または方針として行わない
  'review', // 未確定。確認が済むまで実行しない
])

/**
 * 判断を止めている個別の要因。deny / review の理由をここに列挙する。
 * 「許諾待ち」を1語に潰すと robots・規約・著作権・倫理・技術的ブロックが区別できなくなるため分ける。
 */
export const Constraint = z.enum([
  /** robots.txt が会議録の経路を Disallow している */
  'rep-path-disallowed',
  /**
   * 画面は Allow だが、描画すると裏で Disallow の API を叩く（DiscussNetPremium）。
   * 自動実行する時点で REP の適用対象は crawler であり、実ブラウザを使っても回避にならない。
   */
  'rep-render-still-disallowed',
  /** 利用規約を確認していない */
  'terms-unverified',
  /** 本文の著作権上の扱いが未確定（発言種別・非発言部分・編集著作物性など） */
  'copyright-unverified',
  /** 発行者が AI/LLM クローラを名指しで拒否している（REP 上の適用有無とは別の、意図の尊重） */
  'publisher-ai-opt-out',
  /** CDN 等が UA で拒否する等、技術的に取得できない */
  'technical-block',
  /** 会議録が Web 公開されていない */
  'no-source',
])

/**
 * 取得と再配布は別のゲート。
 * 取得してよいこと（robots・技術）と、正規化して公開してよいこと（著作権・規約）は別問題で、
 * 混ぜると「robots がクリアだから公開してよい」という誤りに繋がる。
 */
export const Gate = z.object({
  /** 取得してよいか */
  fetch: Decision,
  /** 取得したものを正規化して公開してよいか */
  redistribute: Decision,
  constraints: z.array(Constraint),
  /** どの版の判断規則で評価したか */
  policyVersion: z.string(),
  evaluatedAt: z.iso.date(),
  note: z.string().nullable().optional(),
})

export const Robots = z.object({
  verdict: RobotsVerdict,
  aiCrawler: AiCrawler,
  /**
   * 原文証跡（`data/transcripts/observations/robots.json`）への参照。
   * 原文をここに要約して持つと RFC 9309 準拠の再判定ができなくなるため、
   * manifest 側は判定と参照だけを持ち、原文は observations が single source of truth。
   * null は robots.txt を読めなかったことを表す。
   */
  observation: z
    .object({
      requestUrl: z.url(),
      status: z.number().int().nullable(),
      sha256: z.string().nullable(),
      fetchedAt: z.iso.datetime(),
    })
    .nullable(),
  host: z.string().optional(),
})

export const Transcript = z.object({
  systemFamily: SystemFamily,
  /**
   * 取得の起点。**driver はここだけを見る**（entryUrl / host は由来を残すための補助で、
   * 取得先の正ではない）。systemFamily が 'none' のときだけ null を取る。
   */
  transcriptUrl: z.url().nullable(),
  robots: Robots,
  gate: Gate,
  /** 委員会記録も収録しているか。予算の実質審議は委員会で行われるため重要。null = 未確認 */
  hasCommittee: z.boolean().nullable(),
  /** full = 全文記録（逐語）、summary = 要点記録、null = 未確認 */
  recordType: z.enum(['full', 'summary']).nullable(),
  confidence: z.enum(['confirmed', 'probable', 'unverified', 'failed']),
  verifiedAt: z.iso.date().optional(),
  evidenceUrls: z.array(z.url()).optional(),
  notes: z.string().optional(),
  /** DiscussNetPremium のテナント識別子 */
  tenant: z.string().optional(),
  tenantId: z.number().int().optional(),
  /** 調査時に辿った入口。transcriptUrl の由来を残すためのもので取得には使わない */
  entryUrl: z.url().optional(),
  /** robots.txt を取得したホスト。transcriptUrl のホストと一致するとは限らない */
  host: z.string().optional(),
})

/**
 * 配布ファイルが既知のスキーマに沿っているかの実測結果。
 * データセット名は自治体ごとに揺れる（「議会だより」「めぐろ区議会だより」「区議会だより一覧」
 * 「【事業案内】みたか議会だより」）ため、**名称ではなく列構成で判定する**。
 *
 * ⚠️ `fudoki/tokyo-municipal-bulletin-profile/0.1` は fudoki が実測に名前を与えた観測プロファイルで、
 * 公式の標準ではない。デジタル庁の自治体標準オープンデータセット（旧・推奨データセット）の
 * 定義書には広報紙のテーマが存在しないことを確認済み。詳細は src/schema/tokyo-municipal-bulletin-profile.ts。
 */
export const SchemaCheck = z.object({
  standard: z.enum(['fudoki/tokyo-municipal-bulletin-profile/0.1', 'unknown']),
  conformance: z.enum(['conformant', 'variant', 'broken', 'unchecked']),
  columns: z.number().int().nullable().optional(),
  /** 標準に無い追加列。variant の内訳を残す */
  extraColumns: z.array(z.string()).nullable().optional(),
  checkedAt: z.iso.date().optional(),
  note: z.string().nullable().optional(),
})

/** 東京都オープンデータカタログ（CKAN）で見つかった1データセット */
export const OpenDataset = z.object({
  title: z.string(),
  formats: z.array(z.string()),
  /** CKAN のリソース URL。スキームなしが混ざるため取り込み時に正規化する */
  url: z.url().nullable(),
  license: z.string().nullable(),
  /** 同カテゴリで見つかったデータセット数 */
  count: z.number().int().positive(),
  schemaCheck: SchemaCheck.optional(),
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
  policy: z.object({
    version: z.string(),
    decidedAt: z.iso.date(),
    rule: z.string(),
    constraints: z.record(z.string(), z.string()),
  }),
  /** キーは全国地方公共団体コード（6桁） */
  jurisdictions: z.record(z.string().regex(/^\d{6}$/), Jurisdiction),
})

export type Decision = z.infer<typeof Decision>
export type Constraint = z.infer<typeof Constraint>
export type Gate = z.infer<typeof Gate>
export type SystemFamily = z.infer<typeof SystemFamily>
export type RobotsVerdict = z.infer<typeof RobotsVerdict>
export type Transcript = z.infer<typeof Transcript>
export type OpenData = z.infer<typeof OpenData>
export type Jurisdiction = z.infer<typeof Jurisdiction>
export type Manifest = z.infer<typeof Manifest>

/**
 * driver が取得対象を選ぶときの唯一の入口。取得先 URL が必ず引ける形で返す。
 * `gate.fetch === 'allow'` だけを通す（review / deny は含めない）。
 */
export function fetchTargets(m: Manifest): FetchTarget[] {
  return Object.entries(m.jurisdictions).flatMap(([code, j]) => {
    const url = j.transcript.transcriptUrl
    return j.transcript.gate.fetch === 'allow' && url ? [{ code, url, jurisdiction: j }] : []
  })
}


export type FetchTarget = {
  code: string
  url: string
  jurisdiction: Jurisdiction
}
