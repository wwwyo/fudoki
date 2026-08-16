/**
 * # COFOG の割り当て規則
 *
 * **ここから先が fudoki の判断**。三鷹市が言っていないことを付け加える段。
 * Budget Standard Taxonomy が提供するのは COFOG を格納する語彙だけで、
 * 日本の予算科目から COFOG への対応そのものは仕様側に存在しない。
 *
 * ## 状態は2つの軸に分ける
 *
 * 分類の軸（割当済み / 分類不能 / 対象外）と連結の軸（保持 / 消去）は問いが違う。
 * 1つの排他的な状態に畳むと、**分類できなかったもの**と**そもそも分類の対象でないもの**が
 * 混ざり、集計が壊れる。公債費の元金償還は「分類できない」のではなく「対象外」である。
 *
 * 会計間の移転も自動的に対象外にはならない。COFOG には政府の階層間の移転を扱う区分があり、
 * 連結の範囲外へ出る移転や特定の機能に紐づく移転は分類の対象になる。
 * 三鷹市の繰出金は連結の範囲内なので**消去する**が、**分類は受け皿の会計の機能に対応する**。
 *
 * ## 分類不能の割合の低さは合否に使わない
 *
 * 成立範囲を正直に調べることが目的で、割合を目標にすると分類不能を減らす方向に判断が歪む。
 */

/** 使用する版。ディビジョンの値域は `01` から `10` */
export const COFOG_VERSION = 'COFOG 1999'
export const COFOG_SOURCE = {
  name: 'UNSD Classification of the Functions of Government (COFOG)',
  url: 'https://unstats.un.org/unsd/classifications/Family/Detail/4',
}

export const COFOG_DIVISIONS: Record<string, string> = {
  '01': '一般公共サービス',
  '02': '防衛',
  '03': '公共の秩序及び安全',
  '04': '経済業務',
  '05': '環境保護',
  '06': '住宅及び地域アメニティ',
  '07': '保健',
  '08': '娯楽、文化及び宗教',
  '09': '教育',
  '10': '社会保護',
}

/** 分類の軸 */
export type ClassificationStatus = 'assigned' | 'unclassifiable' | 'out-of-scope'
/** 連結の軸 */
export type Consolidation = 'retained' | 'eliminated'

/** 連結の範囲。消去した行に記録する */
export const CONSOLIDATION_SCOPE = '三鷹市の全会計（本パッケージ収録分。下水道事業会計を除く）'

export type Assignment = {
  status: ClassificationStatus
  /** 割当済みのときだけ入る。分類不能と対象外では空にする */
  division: string
  consolidation: Consolidation
  /** どの単位で決まったか。款で決まらないものがどこまで下がったかを測る */
  decidedAtLevel: '会計' | '款' | '項' | '目' | '節' | '（規則なし）'
  basis: string
  /** 消去する行の相手側。受け皿の会計の他会計繰入金を指す */
  counterpartFund: string | null
}

/** 規則が見る行。原典の名称だけを使い、コードには依存しない */
export type BudgetLine = {
  fund: string
  kan: string
  kou: string
  moku: string
  setsu: string
}

type Rule = {
  id: string
  when: (l: BudgetLine) => boolean
  then: Omit<Assignment, 'counterpartFund'> & { counterpartFund?: string }
}

/** 繰出金は消去したうえで、受け皿の会計の機能で分類する */
function transferRule(id: string, mokuKeyword: string, division: string, counterpartFund: string, why: string): Rule {
  return {
    id,
    when: (l) => l.setsu === '繰出金' && l.moku.includes(mokuKeyword),
    then: {
      status: 'assigned',
      division,
      consolidation: 'eliminated',
      decidedAtLevel: '目',
      basis: `同一主体内の会計間繰出。連結時は消去する。分類は受け皿である${counterpartFund}の機能に対応し、${why}`,
      counterpartFund,
    },
  }
}

/**
 * 上から順に見て最初に当たったものを採る。**具体的な規則ほど先に置く。**
 *
 * 当たらなかった行は捨てず、`（規則なし）` として分類不能に落とす（パーサ設計の原則6）。
 * 捨てた瞬間、下流にはその金額が存在しなかったことしか伝わらない。
 */
const RULES: Rule[] = [
  // ── 連結の軸：会計間の繰出 ───────────────────────────────
  transferRule('transfer-kokuho', '国民健康保険事業特別会計繰出金', '07', '国民健康保険事業特別会計', '医療給付を担うため 07 保健'),
  transferRule('transfer-kaigo-service', '介護サービス事業特別会計繰出金', '10', '介護サービス事業特別会計', '介護サービスの提供であり 10 社会保護'),
  transferRule('transfer-kaigo-hoken', '介護保険事業特別会計繰出金', '10', '介護保険事業特別会計', '長期介護の社会保険であり 10 社会保護'),
  transferRule('transfer-kouki', '後期高齢者医療特別会計繰出金', '07', '後期高齢者医療特別会計', '医療給付を担うため 07 保健'),
  {
    id: 'transfer-to-general',
    when: (l) => l.setsu === '繰出金' && l.moku.includes('一般会計繰出金'),
    then: {
      status: 'out-of-scope',
      division: '',
      consolidation: 'eliminated',
      decidedAtLevel: '目',
      basis: '特別会計から一般会計への精算返還。同一主体内の移転として消去する。COFOG の対象である経費・非金融資産への純投資のいずれでもないため分類の対象外',
      counterpartFund: '一般会計',
    },
  },

  // ── 分類の軸：金融取引は対象外 ────────────────────────────
  {
    id: 'debt-principal',
    when: (l) => l.kan === '公債費' && l.moku === '元金',
    then: { status: 'out-of-scope', division: '', consolidation: 'retained', decidedAtLevel: '目', basis: '市債の元金償還。金融負債の返済であり、COFOG の対象である経費・非金融資産への純投資のいずれでもない' },
  },
  {
    id: 'debt-interest',
    when: (l) => l.kan === '公債費' && l.moku === '利子',
    then: { status: 'assigned', division: '01', consolidation: 'retained', decidedAtLevel: '目', basis: '市債利子。COFOG 01.7 公債取引にあたる' },
  },
  {
    id: 'fund-accumulation',
    when: (l) => l.setsu === '積立金',
    then: { status: 'out-of-scope', division: '', consolidation: 'retained', decidedAtLevel: '節', basis: '基金への積立。金融資産の取得であり COFOG の集計対象ではない' },
  },
  {
    id: 'refund',
    when: (l) => l.kou === '償還金及び還付加算金',
    then: { status: 'out-of-scope', division: '', consolidation: 'retained', decidedAtLevel: '項', basis: '過誤納金の還付。歳入の戻しであり経費ではない' },
  },

  // ── 分類の軸：使途が未定 ──────────────────────────────
  {
    id: 'contingency',
    when: (l) => l.kan === '予備費',
    then: { status: 'unclassifiable', division: '', consolidation: 'retained', decidedAtLevel: '款', basis: '予備費。COFOG の対象だが、執行されるまで機能が決まらないため割り当ての根拠が無い' },
  },

  // ── 目まで下げないと決まらないもの ──────────────────────────
  {
    id: 'toshikeikaku-somu',
    when: (l) => l.kou === '都市計画費' && (l.moku === '都市計画総務費' || l.moku === '再開発事業費'),
    then: { status: 'assigned', division: '06', consolidation: 'retained', decidedAtLevel: '目', basis: '都市計画・市街地再開発。COFOG 06.2 地域開発' },
  },
  {
    id: 'toshikeikaku-gairo',
    when: (l) => l.kou === '都市計画費' && l.moku === '街路事業費',
    then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '目', basis: '都市計画道路の整備。COFOG 04.5.1 道路交通' },
  },
  {
    id: 'toshikeikaku-kouen',
    when: (l) => l.kou === '都市計画費' && l.moku === '緑化公園費',
    then: { status: 'assigned', division: '08', consolidation: 'retained', decidedAtLevel: '目', basis: '公園・緑化。COFOG 08.1 レクリエーション及びスポーツのサービス' },
  },
  {
    id: 'toshikeikaku-gesui',
    when: (l) => l.kou === '都市計画費' && l.moku === '下水道事業支出金',
    then: { status: 'assigned', division: '05', consolidation: 'retained', decidedAtLevel: '目', basis: '下水道事業への支出。COFOG 05.2 排水管理。下水道事業会計は本パッケージの収録範囲外なので消去しない' },
  },
  {
    id: 'shogaigakushu-toshokan',
    when: (l) => l.kou === '生涯学習費' && l.moku === '図書館費',
    then: { status: 'assigned', division: '08', consolidation: 'retained', decidedAtLevel: '目', basis: '図書館。COFOG 08.2 文化サービスが図書館を明示的に含むため、教育費の下にあっても 08 に置く' },
  },
  {
    id: 'shogaigakushu-other',
    when: (l) => l.kou === '生涯学習費',
    then: { status: 'assigned', division: '09', consolidation: 'retained', decidedAtLevel: '目', basis: '社会教育（生涯学習総務・青少年育成・生涯学習センター）。COFOG 09.5 水準が定義できない教育。08 文化サービスとの境界は判断であり、2団体目で再検討する' },
  },

  // ── 項で決まるもの ──────────────────────────────────
  { id: 'eisei-hoken', when: (l) => l.kou === '保健衛生費', then: { status: 'assigned', division: '07', consolidation: 'retained', decidedAtLevel: '項', basis: '保健衛生。COFOG 07 保健' } },
  { id: 'eisei-seiso', when: (l) => l.kou === '清掃費', then: { status: 'assigned', division: '05', consolidation: 'retained', decidedAtLevel: '項', basis: 'ごみ処理。COFOG 05.1 廃棄物管理' } },
  { id: 'doboku-kanri', when: (l) => l.kou === '土木管理費', then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '項', basis: '土木の管理部門。COFOG 04.5 運輸の管理にあたる' } },
  { id: 'doboku-doro', when: (l) => l.kou === '道路橋梁費', then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '項', basis: '道路・橋梁。COFOG 04.5.1 道路交通' } },
  { id: 'doboku-kasen', when: (l) => l.kou === '河川費', then: { status: 'assigned', division: '05', consolidation: 'retained', decidedAtLevel: '項', basis: '河川・水路の管理。COFOG は治水を明示的に置いていないため 05 環境保護に寄せた判断で、04 経済業務にも読める' } },
  { id: 'doboku-jutaku', when: (l) => l.kou === '住宅費', then: { status: 'assigned', division: '06', consolidation: 'retained', decidedAtLevel: '項', basis: '住宅。COFOG 06.1 住宅開発' } },
  { id: 'kyoiku-somu', when: (l) => l.kou === '教育総務費' || l.kou === '小学校費' || l.kou === '中学校費', then: { status: 'assigned', division: '09', consolidation: 'retained', decidedAtLevel: '項', basis: '学校教育。COFOG 09.1〜09.2 初等・中等教育' } },
  { id: 'kyoiku-sports', when: (l) => l.kou === 'スポーツ推進費', then: { status: 'assigned', division: '08', consolidation: 'retained', decidedAtLevel: '項', basis: 'スポーツ推進。COFOG 08.1 レクリエーション及びスポーツのサービス' } },

  // ── 款で決まるもの（一般会計） ─────────────────────────────
  { id: 'gikai', when: (l) => l.kan === '議会費', then: { status: 'assigned', division: '01', consolidation: 'retained', decidedAtLevel: '款', basis: '議会。COFOG 01.1 立法機関・行政機関' } },
  { id: 'somu', when: (l) => l.kan === '総務費', then: { status: 'assigned', division: '01', consolidation: 'retained', decidedAtLevel: '款', basis: '総務・徴税・戸籍・選挙・統計・監査。COFOG 01 一般公共サービス' } },
  { id: 'minsei', when: (l) => l.kan === '民生費', then: { status: 'assigned', division: '10', consolidation: 'retained', decidedAtLevel: '款', basis: '社会福祉・児童福祉・生活保護。COFOG 10 社会保護' } },
  { id: 'rodo', when: (l) => l.kan === '労働費', then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '款', basis: '労働諸費。COFOG 04.1.2 一般労働業務' } },
  { id: 'norin', when: (l) => l.kan === '農林費', then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '款', basis: '農業。COFOG 04.2 農林水産業' } },
  { id: 'shoko', when: (l) => l.kan === '商工費', then: { status: 'assigned', division: '04', consolidation: 'retained', decidedAtLevel: '款', basis: '商工業。COFOG 04.7 その他の産業' } },
  { id: 'shobo', when: (l) => l.kan === '消防費', then: { status: 'assigned', division: '03', consolidation: 'retained', decidedAtLevel: '款', basis: '消防。COFOG 03.2 消防サービス' } },

  // ── 会計で決まるもの（特別会計） ────────────────────────────
  { id: 'fund-kokuho', when: (l) => l.fund === '国民健康保険事業特別会計', then: { status: 'assigned', division: '07', consolidation: 'retained', decidedAtLevel: '会計', basis: '国民健康保険。医療給付とその運営であり COFOG 07 保健' } },
  { id: 'fund-kouki', when: (l) => l.fund === '後期高齢者医療特別会計', then: { status: 'assigned', division: '07', consolidation: 'retained', decidedAtLevel: '会計', basis: '後期高齢者医療。医療給付とその運営であり COFOG 07 保健' } },
  { id: 'fund-kaigo-service', when: (l) => l.fund === '介護サービス事業特別会計', then: { status: 'assigned', division: '10', consolidation: 'retained', decidedAtLevel: '会計', basis: '介護サービス事業。COFOG 10.2 高齢' } },
  { id: 'fund-kaigo-hoken', when: (l) => l.fund === '介護保険事業特別会計', then: { status: 'assigned', division: '10', consolidation: 'retained', decidedAtLevel: '会計', basis: '介護保険。長期介護の社会保険であり COFOG 10.2 高齢' } },
]

export function assign(line: BudgetLine): Assignment & { ruleId: string } {
  const hit = RULES.find((r) => r.when(line))
  if (!hit) {
    return {
      ruleId: '(none)',
      status: 'unclassifiable',
      division: '',
      consolidation: 'retained',
      decidedAtLevel: '（規則なし）',
      basis: `どの規則にも当たらなかった（会計=${line.fund} / 款=${line.kan} / 項=${line.kou} / 目=${line.moku} / 節=${line.setsu}）。捨てずに分類不能として残す`,
      counterpartFund: null,
    }
  }
  return { ruleId: hit.id, counterpartFund: null, ...hit.then }
}

/** 報告に規則の一覧を出すため。人が入力と出力を並べて妥当性を判定できる規模に保つ */
export const RULE_IDS = RULES.map((r) => r.id)
