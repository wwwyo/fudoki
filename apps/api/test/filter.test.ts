import { describe, expect, test } from 'bun:test'
import { FilterSyntaxError, filterFingerprint, parseFilter } from '../src/filter'

describe('parseFilter', () => {
  test('quoted and bare values', () => {
    expect(parseFilter('cofog.division = "09" AND fiscalYear = 2023')).toEqual({
      cofogDivision: '09',
      fiscalYear: '2023',
    })
    expect(parseFilter('direction = expenditure')).toEqual({ direction: 'expenditure' })
    expect(parseFilter('phase = "adjusted-before-transfer"')).toEqual({ phase: 'adjusted-before-transfer' })
  })

  test('rejects unsupported syntax', () => {
    expect(() => parseFilter('fiscalYear != 2023')).toThrow(FilterSyntaxError)
    expect(() => parseFilter('fiscalYear = 2023 OR direction = expenditure')).toThrow(FilterSyntaxError)
    expect(() => parseFilter('unknownField = 1')).toThrow(FilterSyntaxError)
    expect(() => parseFilter('fiscalYear = 2023 AND fiscalYear = 2024')).toThrow(FilterSyntaxError)
    expect(() => parseFilter('direction = "somewhere"')).toThrow(FilterSyntaxError)
  })

  test('fingerprint is order-independent and value-sensitive', () => {
    const a = filterFingerprint(parseFilter('cofog.division = "09" AND fiscalYear = 2023'))
    const b = filterFingerprint(parseFilter('fiscalYear = 2023 AND cofog.division = "09"'))
    const c = filterFingerprint(parseFilter('cofog.division = "10" AND fiscalYear = 2023'))
    expect(a).toBe(b)
    expect(a).not.toBe(c)
  })
})
