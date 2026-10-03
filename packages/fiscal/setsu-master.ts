/**
 * 歳出の節マスタ。法定の区分を**適用期間つきの定義**として持つ。
 *
 * 出所は地方自治法施行規則（昭和22年内務省令第29号）第15条第2項の
 * 別記「歳出予算に係る節の区分」。
 * ⚠️ **コードは法律の条文ではなく別記の番号。** 自治体が原典に印字する節コードは
 * 団体独自の振り直しがありうる（多摩市は予備費を29と印字する）ので、
 * 原典との対応は別の宣言（`expenditure_setsu_map`）を介す。
 *
 * 法改正で意味が変わるときは新しい ID を足し、公開済みの ID の意味は変えない。
 * 賃金は平成31年総務省令第37号（令和2年4月1日施行）で削除され、
 * 以降の節番号が繰り上がった。コードも期間も違うため別の定義として持つ。
 */

export const EXPENDITURE_SETSU_LEGAL_BASIS =
  'https://laws.e-gov.go.jp/law/322M40000008029'

export interface ExpenditureSetsu {
  expenditure_setsu_id: string
  code: string
  label: string
  valid_from_fiscal_year: number | null
  valid_to_fiscal_year: number | null
  legal_basis: string
}

/** 令和2年度以降の別記の区分（賃金を除き番号を繰り上げた現行体系）。 */
const CURRENT: [string, string][] = [
  ['01', '報酬'],
  ['02', '給料'],
  ['03', '職員手当等'],
  ['04', '共済費'],
  ['05', '災害補償費'],
  ['06', '恩給及び退職年金'],
  ['07', '報償費'],
  ['08', '旅費'],
  ['09', '交際費'],
  ['10', '需用費'],
  ['11', '役務費'],
  ['12', '委託料'],
  ['13', '使用料及び賃借料'],
  ['14', '工事請負費'],
  ['15', '原材料費'],
  ['16', '公有財産購入費'],
  ['17', '備品購入費'],
  ['18', '負担金、補助及び交付金'],
  ['19', '扶助費'],
  ['20', '貸付金'],
  ['21', '補償、補填及び賠償金'],
  ['22', '償還金、利子及び割引料'],
  ['23', '投資及び出資金'],
  ['24', '積立金'],
  ['25', '寄附金'],
  ['26', '公課費'],
  ['27', '繰出金'],
  ['28', '予備費'],
]

/** 平成31年総務省令第37号による改正前の区分（賃金を第7節として持つ旧体系）。 */
const LEGACY: [string, string][] = [
  ['01', '報酬'],
  ['02', '給料'],
  ['03', '職員手当等'],
  ['04', '共済費'],
  ['05', '災害補償費'],
  ['06', '恩給及び退職年金'],
  ['07', '賃金'],
  ['08', '報償費'],
  ['09', '旅費'],
  ['10', '交際費'],
  ['11', '需用費'],
  ['12', '役務費'],
  ['13', '委託料'],
  ['14', '使用料及び賃借料'],
  ['15', '工事請負費'],
  ['16', '原材料費'],
  ['17', '公有財産購入費'],
  ['18', '備品購入費'],
  ['19', '負担金、補助及び交付金'],
  ['20', '扶助費'],
  ['21', '貸付金'],
  ['22', '補償、補填及び賠償金'],
  ['23', '償還金、利子及び割引料'],
  ['24', '投資及び出資金'],
  ['25', '積立金'],
  ['26', '寄附金'],
  ['27', '公課費'],
  ['28', '繰出金'],
  ['29', '予備費'],
]

const LEGACY_TO = 2019
const CURRENT_FROM = 2020

/** 全体系で共通する定義。現行・旧のどちらでも同じコードと名称なら1行で表す。 */
const SHARED_CODES = new Set(
  CURRENT.filter(([code, label]) =>
    LEGACY.some(([c, l]) => c === code && l === label)
  ).map(([code]) => code)
)

export function expenditureSetsuMaster(): ExpenditureSetsu[] {
  const rows: ExpenditureSetsu[] = []
  for (const [code, label] of CURRENT) {
    rows.push({
      expenditure_setsu_id: `setsu-${code}`,
      code,
      label,
      valid_from_fiscal_year: SHARED_CODES.has(code) ? null : CURRENT_FROM,
      valid_to_fiscal_year: null,
      legal_basis: EXPENDITURE_SETSU_LEGAL_BASIS,
    })
  }
  for (const [code, label] of LEGACY) {
    // 現行体系と同じ定義（コード・名称一致）は現行側の行が全期間を覆う
    if (SHARED_CODES.has(code)) continue
    rows.push({
      expenditure_setsu_id: `setsu-${code}-2019`,
      code,
      label,
      valid_from_fiscal_year: null,
      valid_to_fiscal_year: LEGACY_TO,
      legal_basis: EXPENDITURE_SETSU_LEGAL_BASIS,
    })
  }
  const ids = new Set(rows.map((row) => row.expenditure_setsu_id))
  if (ids.size !== rows.length) throw new Error('Duplicate expenditure_setsu_id')
  const from = (row: ExpenditureSetsu) => row.valid_from_fiscal_year ?? -Infinity
  const to = (row: ExpenditureSetsu) => row.valid_to_fiscal_year ?? Infinity
  for (const a of rows)
    for (const b of rows)
      if (
        a !== b &&
        a.code === b.code &&
        from(a) <= to(b) &&
        from(b) <= to(a)
      )
        throw new Error(`Setsu periods overlap: ${a.code}`)
  return rows.sort((a, b) =>
    a.expenditure_setsu_id.localeCompare(b.expenditure_setsu_id)
  )
}
