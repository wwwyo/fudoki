import { expect, test } from 'bun:test'
import { expenditureSetsuMaster } from './setsu-master'

test('setsu master holds period-scoped legal definitions without version or amount', () => {
  const master = expenditureSetsuMaster()
  expect(master.length).toBe(51)
  expect(new Set(master.map((row) => row.expenditure_setsu_id)).size).toBe(51)
  for (const row of master) {
    expect(row).not.toHaveProperty('version_id')
    expect(row).not.toHaveProperty('amount')
    expect(row.legal_basis).toContain('laws.e-gov.go.jp')
    if (row.valid_from_fiscal_year !== null && row.valid_to_fiscal_year !== null)
      expect(row.valid_from_fiscal_year).toBeLessThanOrEqual(
        row.valid_to_fiscal_year
      )
  }
})
test('the 2019 ordinance change kept 賃金 as a separate definition instead of renumbering it', () => {
  const master = expenditureSetsuMaster()
  const chingin = master.find((row) => row.label === '賃金')!
  expect(chingin.code).toBe('07')
  expect(chingin.valid_to_fiscal_year).toBe(2019)
  const houshou = master.find((row) => row.code === '07' && row.label !== '賃金')!
  expect(houshou.label).toBe('報償費')
  expect(houshou.valid_from_fiscal_year).toBe(2020)
  // 番号が繰り上がった区分は新旧で別の定義。同じコードで期間が重ならない。
  for (const a of master)
    for (const b of master)
      if (a !== b && a.code === b.code)
        expect(
          (a.valid_to_fiscal_year ?? 9999) <
            (b.valid_from_fiscal_year ?? 0) ||
            (b.valid_to_fiscal_year ?? 9999) <
              (a.valid_from_fiscal_year ?? 0)
        ).toBe(true)
})
