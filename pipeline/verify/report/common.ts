/**
 * 層に依存しない報告の型。予算・調達で共通。
 *
 * **画面が読む契約はここが正本**で、生成側（各層の build.ts）がこの形で出す。
 *
 * 生成側と画面が同じ型を見るので、食い違いはコンパイラが捕まえる。
 */

/** 段。**dbt のモデルの置き場がそのまま段になる** */
export type Stage = {
  id: 'origin' | 'ingestion' | 'staging' | 'intermediate' | 'marts'
  label: string
  responsibility: string
  /** fudoki の判断が入る段か。境界はここにある */
  introducesJudgment: boolean
}

export const STAGES: Stage[] = [
  {
    id: 'origin',
    label: '取得元',
    introducesJudgment: false,
    responsibility: '自治体が公開しているファイルそのもの',
  },
  {
    id: 'ingestion',
    label: 'ingestion',
    introducesJudgment: false,
    responsibility:
      '取得元から取り、無加工のまま Parquet で置く。取得 URL・status・SHA-256・取得時刻を添える',
  },
  {
    id: 'staging',
    label: 'staging',
    introducesJudgment: false,
    responsibility: '原典と1対1。列名の付け替えと型付けだけ',
  },
  {
    id: 'intermediate',
    label: 'intermediate',
    introducesJudgment: true,
    responsibility:
      '提供用データの準備。団体間の構造・金額単位の統一、共通科目への対応、COFOG 分類',
  },
  {
    id: 'marts',
    label: 'marts',
    introducesJudgment: false,
    responsibility:
      '利用者に提供するデータの列・粒度を確定する。この repo では CSV に書き出す',
  },
]

/** ノード = dbt のモデル・ソース・seed。手で並べていない */
export type Node = {
  id: string
  label: string
  kind: 'model' | 'source' | 'seed' | 'origin'
  /**
   * どの団体のノードか。null は団体をまたぐ共有ノード（規則表・intermediate）。
   * **生成側が1箇所で付ける** — 画面が id の命名規則を正規表現で推定すると、
   * id の形式を変えたとき絞り込みが黙って壊れる
   */
  jurisdictionCode: string | null
  stage: Stage['id']
  /** 全団体・全年度の行数。intermediate は系統1本を共有するので、ここには他団体の行も入る */
  rows: number | null
  /**
   * 団体 × 年度で数え直した行数。**画面は選んだ団体・年度でここを引くだけ**にする
   * （画面で足し込むと、同じ数字が2通りに計算されていずれ食い違う）。
   *
   * ⚠️ **`rows` では1団体のページを作れない。** intermediate のモデルは全団体を1つの表に
   * 持つので、`rows` をそのまま出すと多摩市のページにも三鷹市の行が混ざった数字が出る
   * （raw・staging・marts は団体ごとなので、同じ図の中で数字の意味が変わる）。
   *
   * - null: 団体にも年度にも依らない規則表（`rows` がすべて）
   * - `byYear` が null: その団体では年度に依らない（年度を持たない表）。
   *   **欠損ではなく「規則は年度に依らない」という事実**なので、0 に潰さない
   */
  rowsByJurisdiction: Record<
    string,
    { total: number; byYear: Record<string, number> | null }
  > | null
  description: string
  /** このノード自身が判断を持ち込むか（規則を適用する intermediate のモデルと、判断を宣言した seed） */
  introducesJudgment: boolean
  /**
   * このノードのデータが判断を含むか。**上流から伝播する。**
   *
   * 2つを分けないと、COFOG を含む派生の配布物が「判断なし」と表示され、
   * 公表資料の書き写しが「判断あり」と表示される（実際にそうなっていた）。
   * 画面が説明している不変条件そのものを、画面が誤って伝えることになる。
   */
  containsJudgment: boolean
  /** 提供用データとして書き出されるファイル。marts 段のノードだけ持つ */
  artifact: string | null
}

/**
 * ノードの行数を、見ている団体と年度で引く。**足し算はしない**（生成側が数え終えている）。
 * 集計（グルーピング・合算）は `lineage.ts` の1箇所で終わらせてあり、
 * 画面はここでその結果から選ぶだけなので、集計のやり方が2通りに分かれない。
 *
 * `scopedToYear` が false なのは、年度を選んでいないときと、
 * そのノードが年度を持たない（規則表）ときの両方。画面はこれを見て
 * 「この数字だけ年度で切れていない」と言える。
 */
export function nodeRows(
  n: Node,
  jurisdictionCode: string,
  fiscalYear: number | null
): { rows: number | null; scopedToYear: boolean } {
  if (n.rowsByJurisdiction === null)
    return { rows: n.rows, scopedToYear: false }
  // ⚠️ **団体で切れる表に自分の行が無いときに `rows` へ落ちない。**
  // 落とすと、その団体が1行も持たないモデル（名称を PDF から起こした団体だけが行を持つ
  // `core_fiscal_account_names` など）に他団体の合計が出る。無いことは 0 行である
  const mine = n.rowsByJurisdiction[jurisdictionCode]
  if (!mine) return { rows: 0, scopedToYear: fiscalYear !== null }
  if (fiscalYear === null || mine.byYear === null)
    return { rows: mine.total, scopedToYear: false }
  return { rows: mine.byYear[String(fiscalYear)] ?? 0, scopedToYear: true }
}

export type Edge = { from: string; to: string; kind: string }

export type Topology = {
  stages: Stage[]
  nodes: Node[]
  edges: Edge[]
  /** 系統の出所。手書きでないことを画面にも出す */
  source: string
}

/** 検査。**紐づけ（binds）も dbt が知っている**（test の depends_on） */
export type Check = {
  name: string
  description: string
  /**
   * 検査の自然文の説明。**`dbt/tests/*.sql` 冒頭のコメントから取る** —
   * 検査が何を見ているかはそこに書いてある。generic test（unique / not_null など）は
   * コメントを持たないので `test_metadata` から組み立てる。
   */
  explanation: string
  binds: string[]
  ok: boolean
  severity: 'error' | 'warn'
  status: string
  failures: number | null
  detail: string
  /**
   * 非 pass の検査で、どの団体の行に当たったか。**dbt の結果文からは読めない**ので、
   * 生成側が compiled SQL を読み直して付ける。結果行が団体コードの列を持てば団体ごとの
   * 件数、持たなければ `cross`（横断・対象特定不能 — どの団体の分かは画面では言えない）。
   */
  attribution?: CheckAttribution
}

/** 非 pass の検査の帰属。`cross` は全団体を束ねる検査で、どの団体の行かを特定できないもの */
export type CheckAttribution = {
  kind: 'jurisdiction' | 'cross'
  /** 団体コードごとの該当行数（kind === 'jurisdiction' のとき） */
  counts?: Record<string, number>
  /** 先頭の該当行（確認用。rows の各要素は columns の並びに対応） */
  columns?: string[]
  rows?: (string | number | null)[][]
}

/** 突合で残った不一致（原典に印字された合計と、抽出した行の合計が合わない箇所） */
export type ExtractMismatch = Record<string, string | number | null>

/** 事業名の抽出器（`extract_projects.py`）の要約 */
export type ProjectNamesExtract = {
  kind: 'project-names'
  projects: number
  /** 原典に印字された階層合計と一致した事業の数 */
  projectsReconciled?: number
  moku: number
  mokuHeadersFound?: number
  mokuNotReconciled?: number
  totalThousandYen: number
  notReconciled?: ExtractMismatch[]
}

/** 事項別明細書の抽出器（`extract_statement.py`）の要約 */
export type StatementExtract = {
  kind: 'statement'
  leaves: number
  /** リーフ項目の印字金額と抽出金額が一致した数 */
  leavesReconciled?: number
  moku: number
  mokuHeadersFound?: number
  mokuNotReconciled?: number
  setsuColumnNotReconciled?: number
  /** 説明欄の段ごとの合計（project / detail など、千円） */
  explanationLevelTotals?: Record<string, number>
  annotationsDropped?: number
  mokuWithoutExplanation?: number
  total: number
  notReconciled?: ExtractMismatch[]
  nameStable?: boolean
}

/** 歳入の科目名称の抽出器（`extract_revenue_accounts.py`）の要約 */
export type RevenueAccountsExtract = {
  kind: 'revenue-accounts'
  moku: number
  named: number
  /** 金額の読み取りまで取れた目の数（OCR の原典は取れないものがある） */
  withAmount?: number
  kan?: number
  duplicateKeys?: number
}

/**
 * どちらの抽出器の要約かを、証跡が名乗る抽出器のパスから決める。
 * ⚠️ **形（どのキーがあるか）で判定しない。** 項目が増えたときに黙って別の枝へ落ちる。
 */
export function extractedKindOf(
  p: SourceInput
): 'project-names' | 'statement' | 'revenue-accounts' | null {
  if (p.extractor?.includes('extract_statement')) return 'statement'
  if (p.extractor?.includes('extract_projects')) return 'project-names'
  if (p.extractor?.includes('extract_revenue_accounts'))
    return 'revenue-accounts'
  return null
}

/**
 * 取得の証跡。原典1リソースにつき1件。
 *
 * ⚠️ **正本の取り込みだけが持つ項目を必須で宣言しない。** 名称を補う抽出物は
 * 原典と1対1ではなく、リソース名も行数も持たない。必須にすると
 * **型検査は通るのに実行時は `undefined`** になり、行数を足した先が黙って `NaN` になる。
 * 任意なら、読む側は `isCanonicalFetch` で絞ってからでないと足せない。
 */
export type SourceInput = {
  jurisdiction_code: string
  fiscal_year: number
  /** ⚠️ **抽出物は名乗らないことがある**（`extract_projects.py` は direction を持たない） */
  direction?: string
  document_kind?: string
  table_id?: string
  /** Same document's independent moku/setsu observation; not an additive fiscal line. */
  observation_role?: string
  /** ⚠️ **正本の取り込みだけが持つ。** 抽出物は `document_title` を名乗る */
  resource_name?: string
  /** 資料（文書）の名。PDF の取得元はリソース名でなく文書名を持つ */
  document_title?: string
  /** カタログ側のデータセット名（リソースの属する箱） */
  dataset_title?: string
  fiscal_year_basis?: string
  /** 直 URL の宣言しか無い取得元は、どうやって URL を決めたかを文章で持つ */
  url_basis?: string
  /** カタログのリソース URL が宣言済みか（名前解決で拾ったか直書きかの区別） */
  resource_url_declared?: boolean
  resource_url_basis?: string
  request_url: string
  /** 原典の公開ページ（取得 URL ではなく人が辿るページ） */
  landing_page?: string
  status?: number
  bytes: number
  sha256: string
  fetched_at?: string
  /** ⚠️ **PDF を原典とする取得元は持たない**（テキストの文字コードという概念が無い） */
  encoding?: string
  /** ⚠️ 表を持つ取得元だけ（CSV と事項別明細書の PDF） */
  header?: string[]
  /** ⚠️ **正本の取り込みだけが持つ。** 抽出物は行数ではなく抽出の要約（`extracted`）を持つ */
  rows?: number
  /**
   * 取得物が原典そのものか。`verbatim` = 原文をそのまま置いた（復元検査が成り立つ）、
   * `extracted` = 抽出した表しか置いていない（復元は成立しない）。
   * 古い証跡は持たない — 無いものは verbatim と同じ扱いにする
   */
  raw_form?: 'verbatim' | 'extracted'
  input_hashes_verified?: boolean
  roundtrip_verified?: boolean
  /** 抽出した取得元だけが持つ。`pipeline/ingestion/fiscal/extract_*.py@<版>` */
  extractor?: string
  /** PDF の収録頁範囲 `[最初, 最後]`（抽出した取得元だけ） */
  pages?: [number, number]
  /** 頁の組版（spread = 見開き2頁で1行） */
  layout?: string
  /** 何を確かめて収録したかの方式名（`hierarchy-totals + name-stability` など） */
  verification?: string
  verification_note?: string
  /** 抽出時に加えた正規化（検証の「何を見ていないか」を説明するため証跡が持つ） */
  normalization?: string[]
  /** 原典の金額の単位（「千円」など）。宣言は dbt_project.yml の fiscal_amounts が正本 */
  source_amount_unit?: string
  /** 再配布の可否とその根拠（取得元ごとに判断している） */
  redistribute?: string
  redistribute_basis?: string
  license_id?: string
  attribution?: string
  /**
   * PDF から起こした取得元だけが持つ、抽出の要約（原典と1対1ではない）。
   *
   * ⚠️ **抽出器ごとに項目が違うので、全部を任意にして1つの形へ潰さない。**
   * 潰すと「どの抽出器由来か」を型が何も言わなくなり、事項別明細書の証跡を
   * 事業名の証跡として読むコードがコンパイルを通ってしまう（`projects` が
   * 常に undefined になり、黙って 0 になる）。読む側は `kind` で分岐すること。
   * ⚠️ **判別子は証跡に無い。** 抽出器が書いた `extractor` のパスから読む側が導く
   * （`extractedKindOf`）。証跡に持たせると、既に commit 済みの取得物を作り直す必要が出る。
   */
  extracted?: ProjectNamesExtract | StatementExtract | RevenueAccountsExtract
}

/** 正本の取り込みの証跡。**行数とリソース名を必ず持つ**（抽出物との違いはここ） */
export type CanonicalFetch = SourceInput & {
  rows: number
  resource_name: string
}

/**
 * その証跡が「正本の取り込み」か。
 *
 * ⚠️ **`extractor` では見分けられない。** 事項別明細書 PDF を原典とする団体
 * （千代田区・昭島市）は正本そのものが抽出器を通るので、`extractor` を持つ。
 * 見分けるのは行数の有無 — 正本の取り込みは CSV でも PDF でも必ず行数を持ち、
 * 名称を補う抽出物は原典と1対1でないので持たない。
 *
 * ⚠️ **戻り値を `boolean` にしない。** 型述語だから、絞り込んでいない証跡から
 * 行数を足すコードがコンパイルを通らなくなる。
 */
export function isCanonicalFetch(p: SourceInput): p is CanonicalFetch {
  return (
    typeof p.rows === 'number' &&
    Number.isFinite(p.rows) &&
    p.resource_name !== undefined
  )
}

/**
 * その証跡が、この direction の「正本の取り込み」か。判別そのものは `isCanonicalFetch`。
 *
 * ⚠️ **direction で絞るだけでは足りない。** 抽出物のうち revenue-accounts も
 * direction を名乗るので、これだけだと正本の合算に混ざる。
 */
function isCanonicalFetchOf(
  p: SourceInput,
  direction: string
): p is CanonicalFetch {
  if (p.direction !== direction) return false
  if (p.observation_role === 'independent-moku-setsu') return false
  if (p.table_id && !p.extractor?.includes('extract_statement')) return false
  if (isCanonicalFetch(p)) return true
  // 捨てる前に、正本らしいのに行数だけ無いものを止める。黙って落とすと
  // 取得元の行数が実際より小さくなり、しかもそれが画面から分からない。
  if (p.resource_name)
    throw new Error(
      `${p.jurisdiction_code} の証跡「${p.resource_name}」に rows が無い（${p.fiscal_year}年度）`
    )
  return false
}

/**
 * 抽出物のソースノードがどの種類かを id で決める。
 * ⚠️ **団体の証跡から抽出物を種類で拾うだけだと、同じ団体に2つの抽出器があるとき
 * （狛江市の事業名と歳入の科目名称）両方のソースノードが同じ数字を出す。**
 */
function extractedSourceKind(
  id: string
): 'project-names' | 'revenue-accounts' | null {
  if (/\.raw_\d{6}_project_names\./.test(id)) return 'project-names'
  if (/\.raw_\d{6}_revenue_accounts\./.test(id)) return 'revenue-accounts'
  return null
}

/**
 * ソースノードにぶら下がる証跡。
 * canonical の取り込みは direction（ソース名）で一致し、抽出物は種類と団体で引く。
 *
 * 報告の生成（`lineage.ts`）と検証画面のローカル・データ口
 * （`apps/web/vite-plugins/local-data.ts`）が同じ規則を使う —
 * 規則を2箇所に書くと片方だけ直したとき証跡の拾い方がズレる。
 */
export function inputsForSource(
  id: string,
  direction: string,
  provenance: SourceInput[]
): {
  ps: SourceInput[]
  kind: 'canonical' | 'project-names' | 'revenue-accounts'
} | null {
  const code = /\.raw_(\d{6})/.exec(id)?.[1]
  if (!code) return null
  const mine = provenance.filter((p) => p.jurisdiction_code === code)
  if (/\.raw_\d{6}_moku_setsu\./.test(id)) {
    const ps = mine.filter((p) => p.observation_role === 'independent-moku-setsu' && isCanonicalFetch(p))
    return ps.length ? { ps, kind: 'canonical' } : null
  }
  if (/\.raw_\d{6}_history\./.test(id)) {
    const ps = mine.filter((p) => p.table_id !== undefined && !p.extractor?.includes('extract_statement'))
    return ps.length ? { ps, kind: 'canonical' } : null
  }
  const canonical = mine.filter((p) => isCanonicalFetchOf(p, direction))
  if (canonical.length > 0) return { ps: canonical, kind: 'canonical' }
  const kind = extractedSourceKind(id)
  if (kind === null) return null
  const ps = mine.filter((p) => extractedKindOf(p) === kind)
  return ps.length === 0 ? null : { ps, kind }
}

/**
 * 原典の文書の種類の語彙（`meta.phase.id` が取り得る値）。
 * 地方自治体の予算関係の文書は当初予算・補正予算・決算の3種で、
 * 1団体の収録はこの中の1種類を原典にする。
 *
 * ⚠️ **行が持つ FDP の予算段階（approved / adjusted / executed）とは別の軸。**
 * 狛江市の決算書は1行が予算現額と執行済額の両方を持つ。`approved`（当初予算）は
 * 宣言済みの id をそのまま使うが、補正予算は行段階の `adjusted` と混ざるので
 * 文書種別側は `supplementary` とする。
 */
export const DOCUMENT_KINDS = [
  { id: 'budget', label: '当初予算' },
  { id: 'supplementary', label: '補正予算' },
  { id: 'settlement', label: '決算' },
] as const
export type DocumentKind = (typeof DOCUMENT_KINDS)[number]['id']

/** どの層の報告でも共通の外枠 */
export type ReportEnvelope = {
  meta: {
    jurisdictionCode: string
    jurisdictionName: string
    documentKind: { id: DocumentKind; label: string }
    license: { id: string; url: string }
    attribution: string
    landingPage: string
    /** 実行時刻ではなく原典の取得時刻。回すたびに差分が出ないようにする */
    generatedAt: string
  }
  summary: {
    total: number
    passed: number
    failed: number
    warned: number
    /**
     * staging → 配布物で行が失われていないか。**判定は生成側で行う** —
     * 配布物は1行に複数の金額（狛江市は予算現額・執行済額など3つ）を展開するので、
     * stg と pkg の行数の単純比較は多金額の団体で必ず「不一致」と嘘をつく。
     * 期待値（stg 行数 × 金額の数）は dbt_project.yml の宣言を知る生成側にしか計算できない
     */
    rowsPreserved: boolean
  }
  topology: Topology
  /** ⚠️ **正本の取り込みだけ。** 抽出物は団体のディレクトリの外にあり、ここには来ない
   *（保証を作っているのは `pipeline/verify/report/fiscal/build.ts` の glob。そこで検査する） */
  ingestion: CanonicalFetch[]
  checks: Check[]
}
