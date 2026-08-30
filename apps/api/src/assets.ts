/**
 * 静的アセット（パーティション JSON と配布物の写し）の読み口と、ファイル形式の型。
 * 形式は build.ts が書き、ここが読む。**両者はこの型で合意する。**
 */
import type { Budget, Jurisdiction, StoredBudgetLine, StoredCrossBudgetLine } from './contract'

/**
 * KV namespace binding の最小型。`@cloudflare/workers-types` はこの repo に入れていない
 * （tsconfig の types は `@types/bun` のみ）ので、既存の `ASSETS` と同じく使う形だけ手書きする。
 */
export interface KVNamespaceLike {
  get(key: string): Promise<string | null>
  put(key: string, value: string): Promise<void>
}

/**
 * Rate Limiting binding の最小型。`limit()` は成功/失敗の boolean しか返さない
 * （残量やウィンドウ長は取れない）。カウンターはデータセンターごとであり、
 * グローバルな厳密上限にはならない ── ここで実現しているのは濫用の抑制であって、
 * 課金保護のような厳密な上限ではない。
 */
export interface RateLimiterLike {
  limit(options: { key: string }): Promise<{ success: boolean }>
}

export interface Env {
  ASSETS: { fetch(input: Request | URL | string): Promise<Response> }
  /** ベータ用 API キー。KV のキーが SHA-256(生のキー)、値が ApiKeyEntry の JSON（src/lib/apiKey.ts） */
  API_KEYS: KVNamespaceLike
  /** キー無し（匿名）リクエスト用。IP のハッシュをキーにして呼ぶ */
  RATE_LIMIT_ANONYMOUS: RateLimiterLike
  /** 有効な API キー付きリクエスト用。キーIDをキーにして呼ぶ */
  RATE_LIMIT_AUTHENTICATED: RateLimiterLike
}

export type JurisdictionsFile = {
  revision: string
  jurisdictions: Jurisdiction[]
  /** 収録している全 budget（id 昇順）。カバレッジの正体 */
  budgets: Budget[]
}
export type LinesChunkFile = { revision: string; hasNext: boolean; lines: StoredBudgetLine[] }
export type CofogChunkFile = { revision: string; hasNext: boolean; lines: StoredCrossBudgetLine[] }
export type FilesFile = {
  revision: string
  files: Record<string, Record<string, { sha256: string; size: number; contentType: string }>>
}

/** 集計の1セル分の値（`AggBudgetsAsset` / `AggCrossAsset` 共通の下位構造） */
export type AggStat = { amount: number; lineCount: number }

/**
 * 単一 budget（団体×年度）の COFOG 集計アセット。
 * `agg/{団体}/{年度}/{direction}/{phase}/{fund}/cofog-{depth}.json` の中身。
 * `total` はこの資産の範囲（direction・phase・fund）に閉じた合計 ── `cells` と `residual` の合計に一致する。
 */
export type AggBudgetsAsset = {
  revision: string
  cells: { code: string; label: string; amount: number; lineCount: number }[]
  residual: { unclassifiable: AggStat; outOfScope: AggStat; notDescended: AggStat }
  total: AggStat
  consolidation: { retained: AggStat; eliminated: AggStat }
}

/**
 * 年度横断の COFOG 集計アセット。`agg/cross/{年度}/{direction}/{phase}/cofog-{depth}.json` の中身。
 * fund は選べない（団体を絞らないと fund を指定できないため、常に全会計合算）。
 * `omittedBudgets` は、その年度に予算はあるがこの phase を持たない団体（design doc の `omitted`）。
 *
 * ⚠️ `residual` は団体ごとに持つ（`residualByJurisdiction`）。`cells` は `jurisdiction` を軸に
 * 必須にしているのに、残余だけ全団体で1つに合算すると「団体をまたいで足さない」を残余だけが破る
 * （PR #27 レビュー指摘。団体ごとに `cells + residual` を復元できなくなる）。
 */
export type AggCrossAsset = {
  revision: string
  cells: { jurisdiction: string; jurisdictionLabel: string; code: string; label: string; amount: number; lineCount: number }[]
  residualByJurisdiction: Record<string, { unclassifiable: AggStat; outOfScope: AggStat; notDescended: AggStat }>
  consolidation: { retained: AggStat; eliminated: AggStat }
  includedBudgets: string[]
  omittedBudgets: { budget: string; code: 'PHASE_NOT_AVAILABLE' }[]
}

/**
 * 単一 budget の階層（款・項・目）集計。`agg/{団体}/{年度}/{direction}/{phase}/{fund}/hierarchy/{親のパス}.json`。
 * fund は必ず特定の会計コード（"all" は無し）── 款・項のコードは会計内でしか一意でなく、
 * COFOG のような fudoki の判断による正規化を経ていないため、会計をまたいで同じコードを合算すると
 * 別カテゴリを1つのセルへ混ぜてしまう（design doc は言及していない、この実装の判断）。
 * `total` は cells の合計に一致する（このアセットに COFOG の残余概念は無いので residual は持たない）。
 */
export type AggHierarchyAsset = {
  revision: string
  childLevel: 'kan' | 'kou' | 'moku'
  cells: { code: string; label: string | null; amount: number; lineCount: number }[]
  total: AggStat
}

/**
 * 単一 budget の階層×COFOG（division 固定）の2軸集計。
 * `agg/{団体}/{年度}/{direction}/{phase}/{fund}/hierarchy-cofog/{親のパス}.json`。
 */
export type AggHierarchyCofogAsset = {
  revision: string
  childLevel: 'kan' | 'kou' | 'moku'
  cells: { code: string; label: string | null; cofogDivision: string; cofogLabel: string; amount: number; lineCount: number }[]
  residual: { unclassifiable: AggStat; outOfScope: AggStat; notDescended: AggStat }
  total: AggStat
}

/** fiscalYear 軸の1セルが持つ会計範囲（design doc「年度を軸にしたときは、セルごとに fundScope を持たせる」） */
export type AggYearsFundScope = {
  funds: { code: string; label: string | null }[]
  consolidation: { retained: AggStat; eliminated: AggStat }
}

/**
 * 単一団体の年度横断（COFOG 無し）。`agg/{団体}/years/{direction}/{phase}/{fund}/total.json`。
 * `omittedYears` は、その団体にその年度の予算はあるが phase または fund を持たない年度
 * （design doc「指定した段階を持たない年度は omitted に enum のコードで残す」）。
 *
 * `total` と `fundScope` は範囲全体（全 `cells`）の要約で、ページングの対象から分離してある。
 * procedure がページ後の `cells` から毎回作り直すと、`pageSize` を変えるだけで値が変わってしまう
 * （PR #27 レビュー指摘）ため、ここに一度だけ持つ。
 */
export type AggYearsTotalAsset = {
  revision: string
  cells: { fiscalYear: string; amount: number; lineCount: number; fundScope: AggYearsFundScope }[]
  total: AggStat
  fundScope: AggYearsFundScope
  omittedYears: { fiscalYear: string; code: 'PHASE_NOT_AVAILABLE' | 'FUND_NOT_AVAILABLE' }[]
}

/**
 * 名称索引の1エントリ（design doc「名称の検索」）。**索引の単位は名称であって明細ではない**。
 * 同じ (field, level, value, nameSource) を持つ明細をこのエントリの下へ束ね、
 * 明細のレコード（hierarchy・amounts）は丸ごと持たず、budgetLineId への参照（refs）だけを持つ。
 *
 * ⚠️ 以前は明細1行 × マッチしたレベル数ぶんエントリを複製し、そのたびに hierarchy・amounts を
 * 丸ごとコピーしていた（2026-08-31 実測で 82MB/98チャンクに膨れ、「いじめ」6件を得るのに
 * 60回超のページングが要った）。名称の異なり数は 2,184 件（`setsu` 系と `fund` を除く）しかなく、
 * 明細を単位にする理由が無い。
 *
 * refs から hierarchy・amounts を引くときは budgetLineId をパースする
 * （`{jurisdiction}:{fiscalYear}:{direction}:...` の形。parseBudgetLineId 参照）。
 * jurisdiction・fiscalYear・direction は budgetLineId から機械的に決まるので ref に重複させない。
 * fund は budgetLineId から決まらないので ref が持つ。
 */
export type NameIndexRef = {
  budgetLineId: string
  fund: { code: string; label: string | null }
}
export type NameIndexEntry = {
  field: 'accountLabel' | 'projectName'
  level: string
  value: string
  nameSource: 'canonical' | 'judgment'
  refs: NameIndexRef[]
}
/**
 * `search/all/{chunk}.json` の中身。エントリは (field, level, value, nameSource) の昇順
 * （chunk 分割の安定性のためだけの順序 ── 応答の並び順は procedure 側が budgetLineId で作り直す）。
 * 各エントリの refs は budgetLineId 昇順。
 */
export type NameIndexChunkFile = { revision: string; hasNext: boolean; lines: NameIndexEntry[] }

/**
 * 単一団体の年度横断×COFOG（division 固定）。`agg/{団体}/years/{direction}/{phase}/{fund}/cofog-division.json`。
 *
 * `total` と `fundScope` は範囲全体（全年度・全 division）の要約。`fundScope` は年度ごとに
 * 同じ値を複数の division セルへ複製しているので、procedure がページ後の `cells` を単純に
 * 足し込むと年度内の division 数だけ連結の内訳が水増しされる（PR #27 レビュー指摘）。
 * ここで年度単位に一度だけ集計しておく。
 */
export type AggYearsCofogDivisionAsset = {
  revision: string
  cells: {
    fiscalYear: string
    cofogDivision: string
    cofogLabel: string
    amount: number
    lineCount: number
    fundScope: AggYearsFundScope
  }[]
  /** 年度ごとの COFOG 残余（cells には現れない unclassifiable / out-of-scope / notDescended） */
  residualByYear: Record<string, { unclassifiable: AggStat; outOfScope: AggStat; notDescended: AggStat }>
  total: AggStat
  fundScope: AggYearsFundScope
  omittedYears: { fiscalYear: string; code: 'PHASE_NOT_AVAILABLE' | 'FUND_NOT_AVAILABLE' }[]
}

/** アセットのパスは binding には URL として渡す（ホスト名は何でもよい） */
export async function readAsset(env: Env, path: string): Promise<Response> {
  return env.ASSETS.fetch(new URL(path, 'https://assets.internal/').toString())
}

export async function readJsonAsset<T>(env: Env, path: string): Promise<T | null> {
  const res = await readAsset(env, path)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`asset read failed: ${path} -> ${res.status}`)
  return (await res.json()) as T
}

/**
 * パーティションレイアウトの唯一の定義。書き手（build.ts）も読み手（procedure）も
 * ここを経由し、パス文字列を独立に組み立てない。
 * family はページングの pageToken に封入される系列名（拡張子なし）。
 */
/**
 * 会計コードをパスセグメントへ変換する。空文字（多摩市など、原典がコード自体を持たない団体）は
 * 空セグメントになると `//` で読めなくなるので固定トークンに退避する。
 * 実在の会計コードがこのトークンと衝突しないことは build.ts の検査が見る。
 */
export const EMPTY_FUND_SEGMENT = '_blank_'
export function fundSegment(fund: string): string {
  return fund === '' ? EMPTY_FUND_SEGMENT : fund
}

export const paths = {
  jurisdictions: 'meta/jurisdictions.json',
  files: 'meta/files.json',
  linesFamily: (jurisdiction: string, fiscalYear: string, direction: string) =>
    `lines/${jurisdiction}/${fiscalYear}-${direction}`,
  chunk: (family: string, chunk: number) => `${family}/${chunk}.json`,
  cofogFamily: (division: string, fiscalYear: string | undefined) =>
    fiscalYear === undefined ? `cofog/${division}/all` : `cofog/${division}/${fiscalYear}`,
  passthrough: (jurisdiction: string, file: string) => `datapackages/${jurisdiction}/${file}`,
  /** 単一 budget（団体×年度）の COFOG 集計。design doc「引ける集計の一覧」の1行目 */
  aggBudget: (jurisdiction: string, fiscalYear: string, direction: string, phase: string, fund: string, depth: 'division' | 'group' | 'class') =>
    `agg/${jurisdiction}/${fiscalYear}/${direction}/${phase}/${fundSegment(fund)}/cofog-${depth}.json`,
  /** 年度横断の COFOG 集計（fund は選べないので常に全会計合算）。design doc「引ける集計の一覧」の最終行 */
  aggCross: (fiscalYear: string, direction: string, phase: string, depth: 'division' | 'group' | 'class') =>
    `agg/cross/${fiscalYear}/${direction}/${phase}/cofog-${depth}.json`,
  /**
   * 単一 budget の階層集計。design doc「引ける集計の一覧」2行目。`parentPath` は
   * hierarchyParentPathString の出力（"root" / "kan=10" / "kan=10/kou=04"）で、
   * そのまま追加のパスセグメントになる（"/" を含みうる）。
   */
  aggHierarchy: (jurisdiction: string, fiscalYear: string, direction: string, phase: string, fund: string, parentPath: string) =>
    `agg/${jurisdiction}/${fiscalYear}/${direction}/${phase}/${fundSegment(fund)}/hierarchy/${parentPath}.json`,
  /** 単一 budget の階層×COFOG（division）の2軸集計。design doc「引ける集計の一覧」3行目 */
  aggHierarchyCofog: (jurisdiction: string, fiscalYear: string, direction: string, phase: string, fund: string, parentPath: string) =>
    `agg/${jurisdiction}/${fiscalYear}/${direction}/${phase}/${fundSegment(fund)}/hierarchy-cofog/${parentPath}.json`,
  /** 単一団体の年度横断（COFOG 無し）。design doc「引ける集計の一覧」4行目 */
  aggYearsTotal: (jurisdiction: string, direction: string, phase: string, fund: string) =>
    `agg/${jurisdiction}/years/${direction}/${phase}/${fundSegment(fund)}/total.json`,
  /** 単一団体の年度横断×COFOG（division）。design doc「引ける集計の一覧」5行目 */
  aggYearsCofogDivision: (jurisdiction: string, direction: string, phase: string, fund: string) =>
    `agg/${jurisdiction}/years/${direction}/${phase}/${fundSegment(fund)}/cofog-division.json`,
  /**
   * 名称索引の系列（design doc「名称の検索」）。団体ごとの単一ファイルにせず、
   * 明細チャンクと同じく分割する。全団体を横断する1系列 ── budgetLineId が
   * `{6桁団体コード}:...` で始まるため、文字列昇順ソートが団体をまたいでも
   * 安定した全体順序になる（cofogFamily が division 単位で複数団体を束ねるのと同じ考え方）。
   */
  searchAll: 'search/all',
}
