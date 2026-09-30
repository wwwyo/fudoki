import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  TABLES,
  TABLE_KEYS,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { finalizeCandidate } from '../fdp/manifest'
import { sha256 } from '../release'

/** Synthetic, redistributable fiscal data; it does not stand in for a full dbt run. */
export async function fixture(
  directory: string,
  releaseId: string,
  amount = 100,
  rows = 501
): Promise<ReleaseManifest> {
  const tables: Record<(typeof TABLES)[number], Record<string, unknown>[]> = {
    jurisdictions: [
      {
        jurisdiction_code: '000001',
        name: '検証用の架空団体',
        ocd_id: 'ocd-division/country:jp/fixture:1',
        caveats_json: '[]',
      },
    ],
    fiscal_datasets: [
      {
        dataset_id: 'fixture-dataset',
        jurisdiction_code: '000001',
        fiscal_year: 2026,
        direction: 'expenditure',
        document_kind: 'settlement',
        origin_sha256: 'c'.repeat(64),
        phases_json: '["executed"]',
        source_json: JSON.stringify({
          documentLabel: '架空の決算',
          landingPage: 'https://example.org/fixture',
          licenseId: 'CC0-1.0',
          attribution: 'Synthetic fixture',
          rawForm: 'synthetic',
        }),
        structure_json: JSON.stringify({
          hierarchy: ['moku'],
          dimensions: [],
          funds: [{ code: '01', label: '一般会計' }],
        }),
        line_count: rows,
      },
    ],
    fiscal_lines: [],
    amounts: [],
    cofog: [],
    line_hierarchy: [],
    line_dimensions: [],
    names: [],
  }
  for (let i = 0; i < rows; i++) {
    const id = 'fixture:' + String(i).padStart(6, '0')
    tables.fiscal_lines.push({
      fiscal_line_id: id,
      dataset_id: 'fixture-dataset',
      source_row: i + 1,
      fund_code: '01',
      fund_label: '一般会計',
    })
    tables.amounts.push({
      fiscal_line_id: id,
      phase: 'executed',
      value: amount,
      source_amount: amount,
      source_amount_unit: '円',
      is_primary: 1,
    })
    tables.cofog.push({
      fiscal_line_id: id,
      status: 'assigned',
      division: '09',
      group: '09.1',
      class: '09.1.1',
      consolidation: 'retained',
      decided_at_level: '目',
      rule_id: 'fixture-rule',
      basis: '検証用の分類',
      counterpart_fund: '',
    })
    tables.line_hierarchy.push({
      fiscal_line_id: id,
      ordinal: 0,
      level: 'moku',
      code: '001',
      label: '教育',
      name_source: 'canonical',
    })
    tables.names.push({
      fiscal_line_id: id,
      name_kind: 'hierarchy',
      level: 'moku',
      value: '教育',
      name_source: 'canonical',
      basis: '',
    })
  }
  await mkdir(join(directory, 'api'), { recursive: true })
  await mkdir(join(directory, 'fiscal/000001'), { recursive: true })
  const validation: {
    tables: Record<string, { rows: number; sha256: string }>
    scopeTotals: unknown[]
  } = {
    tables: {},
    scopeTotals: [['fixture-dataset', 'executed', rows, rows * amount]],
  }
  for (const table of TABLES) {
    const keys = TABLE_KEYS[table]
    tables[table].sort((a, b) => {
      for (const key of keys) {
        if (a[key] === b[key]) continue
        return a[key]! < b[key]! ? -1 : 1
      }
      return 0
    })
    const body = tables[table].map((row) => JSON.stringify(row) + '\n').join('')
    await writeFile(join(directory, 'api', table + '.jsonl'), body)
    validation.tables[table] = {
      rows: tables[table].length,
      sha256: sha256(body),
    }
  }
  await writeFile(
    join(directory, 'fiscal/000001/expenditure.csv'),
    'fiscal_line_id,value\n' +
      tables.fiscal_lines
        .map((row) => `${row.fiscal_line_id},${amount}\n`)
        .join('')
  )
  return finalizeCandidate(
    directory,
    {
      releaseId,
      codeRevision: 'a'.repeat(40),
      codeFingerprint: 'b'.repeat(64),
      inputFingerprint: 'c'.repeat(64),
      judgmentFingerprint: 'd'.repeat(64),
      queryFingerprint: 'e'.repeat(64),
    },
    validation
  )
}
