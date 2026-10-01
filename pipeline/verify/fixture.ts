import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  TABLES,
  TABLE_KEYS,
  type CandidateManifest,
} from '@fudoki/data-contracts'
import { finalizeCandidate } from '../fdp/manifest'
import { sha256 } from '../release'

/** Synthetic municipal records exercise storage and delivery independently of real inputs. */
export async function fixture(
  directory: string,
  buildId: string,
  amount = 100,
  rows = 501,
  jurisdictionName = '検証用の架空団体',
  code = '000001'
): Promise<CandidateManifest> {
  const tables = Object.fromEntries(
    TABLES.map((table) => [table, []])
  ) as unknown as Record<(typeof TABLES)[number], Record<string, unknown>[]>
  tables.fiscal_datasets.push({
    dataset_id: `${code}:settlement`,
    jurisdiction_code: code,
    fiscal_year: 2026,
    direction: 'expenditure',
    document_kind: 'settlement',
    origin_sha256: 'c'.repeat(64),
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
    amendment_number: null,
    effective_at: null,
    source_amount_kind: 'executed',
    coverage_json: '{"budgetHistory":"unconfirmed"}',
  })
  for (let index = 0; index < rows; index++) {
    const id = `${code}:${String(index).padStart(6, '0')}`
    tables.fiscal_settlement_expenditure_lines.push({
      fiscal_line_id: id,
      dataset_id: `${code}:settlement`,
      source_row: index + 1,
      fund_code: '01',
      fund_label: '一般会計',
      amount,
      consolidation: 'retained',
      counterpart_fund: '',
      cofog_code: '09.1.1',
      cofog_status: 'assigned',
      cofog_basis: '検証用の分類',
    })
    tables.fiscal_settlement_expenditure_line_hierarchy.push({
      fiscal_line_id: id,
      ordinal: 0,
      level: 'moku',
      code: '001',
      label: '教育',
      name_source: 'canonical',
    })
    tables.fiscal_settlement_expenditure_line_names.push({
      fiscal_line_id: id,
      name_kind: 'hierarchy',
      level: 'moku',
      value: '教育',
      name_source: 'canonical',
      basis: '',
    })
  }
  await mkdir(join(directory, 'api'), { recursive: true })
  const writeRows = (name: string, values: Record<string, unknown>[]) =>
    writeFile(
      join(directory, 'api', name + '.jsonl'),
      values.map((row) => JSON.stringify(row) + '\n').join('')
    )
  await writeRows('cofog_codes', [
    { code: '09', label: '教育', level: 'division', parent_code: null },
    {
      code: '09.1',
      label: '就学前教育及び初等教育',
      level: 'group',
      parent_code: '09',
    },
    {
      code: '09.1.1',
      label: '検証用の小分類',
      level: 'class',
      parent_code: '09.1',
    },
  ])
  await writeRows('jurisdictions', [
    {
      jurisdiction_code: code,
      name: jurisdictionName,
      ocd_id: `ocd-division/country:jp/fixture:${code}`,
    },
  ])
  await writeRows('jurisdiction_metadata', [
    {
      jurisdiction_code: code,
      name_snapshot: jurisdictionName,
      ocd_id_snapshot: `ocd-division/country:jp/fixture:${code}`,
      caveats_json: '[]',
    },
  ])
  const validation = {
    tables: {} as Record<string, { rows: number; sha256: string }>,
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
  await mkdir(join(directory, 'fiscal', code), { recursive: true })
  await writeFile(
    join(directory, 'fiscal', code, 'settlement_expenditure.csv'),
    'fiscal_line_id,amount\n' +
      tables.fiscal_settlement_expenditure_lines
        .map((row) => `${row.fiscal_line_id},${row.amount}\n`)
        .join('')
  )
  await writeFile(
    join(directory, 'fiscal', code, 'datapackage.json'),
    JSON.stringify({
      resources: [
        { name: 'settlement_expenditure', path: 'settlement_expenditure.csv' },
      ],
    })
  )
  return finalizeCandidate(
    directory,
    {
      releaseId: buildId,
      codeRevision: 'a'.repeat(40),
      codeFingerprint: 'b'.repeat(64),
      inputFingerprint: 'c'.repeat(64),
      judgmentFingerprint: 'd'.repeat(64),
      queryFingerprint: 'e'.repeat(64),
    },
    validation
  )
}
