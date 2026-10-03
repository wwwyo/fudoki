import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  TABLES,
  TABLE_KEYS,
  type CandidateManifest,
} from '@fudoki/data-contracts'
import { EXPENDITURE_SETSU_LEGAL_BASIS } from '@fudoki/fiscal/setsu-master'
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
  tables.fiscal_datasets.push({
    dataset_id: `${code}:budget`,
    jurisdiction_code: code,
    fiscal_year: 2026,
    direction: 'expenditure',
    document_kind: 'budget',
    origin_sha256: 'd'.repeat(64),
    source_json: JSON.stringify({
      documentLabel: '架空の当初予算',
      landingPage: 'https://example.org/fixture-budget',
      licenseId: 'CC0-1.0',
      attribution: 'Synthetic fixture',
      rawForm: 'synthetic',
    }),
    structure_json: JSON.stringify({
      hierarchy: ['fund', 'kan', 'kou', 'moku', 'jigyo', 'setsu', 'saisetsu'],
      dimensions: [],
      funds: [{ code: '01', label: '一般会計' }],
    }),
    line_count: 3,
    amendment_number: null,
    effective_at: null,
    source_amount_kind: 'initial',
    coverage_json: '{"budgetHistory":"unconfirmed"}',
  })
  tables.fiscal_datasets.push({
    dataset_id: `${code}:supplementary`,
    jurisdiction_code: code,
    fiscal_year: 2026,
    direction: 'expenditure',
    document_kind: 'supplementary',
    origin_sha256: 'e'.repeat(64),
    source_json: JSON.stringify({
      documentLabel: '架空の補正予算',
      landingPage: 'https://example.org/fixture-supplementary',
      licenseId: 'CC0-1.0',
      attribution: 'Synthetic fixture',
      rawForm: 'synthetic',
    }),
    structure_json: JSON.stringify({
      hierarchy: ['fund', 'kan', 'kou', 'moku', 'jigyo', 'setsu'],
      dimensions: [],
      funds: [{ code: '01', label: '一般会計' }],
    }),
    line_count: 2,
    amendment_number: 1,
    effective_at: '2026-06-01',
    source_amount_kind: 'delta',
    coverage_json: '{"budgetHistory":"unconfirmed"}',
  })
  const itemPath = JSON.stringify([
    { level: 'fund', code: '01', label: '一般会計', nameSource: 'canonical' },
    { level: 'kan', code: '01', label: '議会費', nameSource: 'canonical' },
    { level: 'kou', code: '01', label: '議会費', nameSource: 'canonical' },
    { level: 'moku', code: '001', label: '議会費', nameSource: 'canonical' },
    { level: 'jigyo', code: '', label: '検証事業', nameSource: 'canonical' },
  ])
  tables.fiscal_expenditure_budget_items.push(
    {
      budget_item_id: `b-aggregated-${code}`,
      jurisdiction_code: code,
      fiscal_year: 2026,
      fund_code: '01',
      fund_label: '一般会計',
      expenditure_setsu_id: 'setsu-12',
      line_granularity: 'expenditure_setsu',
      account_path_json: itemPath,
      dimensions_json: '[]',
      names_json: JSON.stringify([
        {
          kind: 'hierarchy',
          level: 'jigyo',
          value: '検証事業',
          nameSource: 'canonical',
          basis: '',
        },
        {
          kind: 'hierarchy',
          level: 'setsu',
          value: '委託料',
          nameSource: 'canonical',
          basis: '',
        },
      ]),
      initial_state: 'recorded',
    },
    {
      budget_item_id: `b-origin-${code}`,
      jurisdiction_code: code,
      fiscal_year: 2026,
      fund_code: '01',
      fund_label: '一般会計',
      expenditure_setsu_id: null,
      line_granularity: 'origin_line',
      account_path_json: itemPath,
      dimensions_json: '[]',
      names_json: '[]',
      initial_state: 'recorded',
    }
  )
  tables.fiscal_initial_expenditure_budget_lines.push(
    {
      fiscal_line_id: `${code}:budget:agg0001`,
      dataset_id: `${code}:budget`,
      budget_item_id: `b-aggregated-${code}`,
      source_row: 10,
      amount: 100,
      details_json: JSON.stringify([
        {
          path: [{ level: 'saisetsu', code: '01', label: '調査委託' }],
          amount: 60,
          fiscalLineId: `${code}:budget:000010`,
          sourceRow: 10,
        },
        {
          path: [{ level: 'saisetsu', code: '02', label: '設計委託' }],
          amount: 40,
          fiscalLineId: `${code}:budget:000011`,
          sourceRow: 11,
        },
      ]),
      consolidation: 'retained',
      counterpart_fund: '',
      cofog_code: '01.1.1',
      cofog_status: 'assigned',
      cofog_basis: '検証用の分類',
    },
    {
      fiscal_line_id: `${code}:budget:000012`,
      dataset_id: `${code}:budget`,
      budget_item_id: `b-origin-${code}`,
      source_row: 12,
      amount: 50,
      details_json: JSON.stringify([
        {
          path: [],
          amount: 50,
          fiscalLineId: `${code}:budget:000012`,
          sourceRow: 12,
        },
      ]),
      consolidation: 'retained',
      counterpart_fund: '',
      cofog_code: null,
      cofog_status: 'unclassifiable',
      cofog_basis: '検証用の未分類',
    }
  )
  tables.fiscal_expenditure_budget_changes.push(
    {
      change_id: `c-increase-${code}`,
      dataset_id: `${code}:supplementary`,
      budget_item_id: `b-aggregated-${code}`,
      amount_delta: 30,
      details_json: JSON.stringify([
        {
          path: [{ level: 'saisetsu', code: '01', label: '調査委託' }],
          amount: 30,
          fiscalLineId: `${code}:supplementary:000001`,
          sourceRow: 1,
        },
      ]),
      change_kind: 'supplementary',
      effective_at: '2026-06-01',
      sequence: 1,
      source_row: 1,
      counterpart_budget_item_id: null,
      carryover_from_year: null,
      carryover_to_year: null,
      cofog_code: '01.1.1',
      cofog_status: 'assigned',
      cofog_basis: '検証用の分類',
    },
    {
      change_id: `c-decrease-${code}`,
      dataset_id: `${code}:supplementary`,
      budget_item_id: `b-aggregated-${code}`,
      amount_delta: -10,
      details_json: JSON.stringify([
        {
          path: [{ level: 'saisetsu', code: '02', label: '設計委託' }],
          amount: -10,
          fiscalLineId: `${code}:supplementary:000002`,
          sourceRow: 2,
        },
      ]),
      change_kind: 'supplementary',
      effective_at: '2026-07-01',
      sequence: 1,
      source_row: 2,
      counterpart_budget_item_id: null,
      carryover_from_year: null,
      carryover_to_year: null,
      cofog_code: '01.1.1',
      cofog_status: 'assigned',
      cofog_basis: '検証用の分類',
    }
  )
  tables.fiscal_expenditure_settlement_links.push({
    budget_item_id: `b-aggregated-${code}`,
    settlement_line_id: `${code}:000000`,
    match_status: 'unconfirmed',
    match_group_id: `g-aggregated-${code}`,
    basis: '検証用の対応（確認前）',
  })
  await mkdir(join(directory, 'api'), { recursive: true })
  const writeRows = (name: string, values: Record<string, unknown>[]) =>
    writeFile(
      join(directory, 'api', name + '.jsonl'),
      values.map((row) => JSON.stringify(row) + '\n').join('')
    )
  await writeRows('cofog_master', [
    { code: '01', label: '一般公的サービス', level: 'division', parent_code: null },
    {
      code: '01.1',
      label: '執行及び立法機関',
      level: 'group',
      parent_code: '01',
    },
    {
      code: '01.1.1',
      label: '検証用の小分類',
      level: 'class',
      parent_code: '01.1',
    },
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
  await writeRows('jurisdiction_master', [
    {
      jurisdiction_code: code,
      name: jurisdictionName,
      ocd_id: `ocd-division/country:jp/fixture:${code}`,
    },
  ])
  await writeRows('fiscal_expenditure_setsu_master', [
    {
      expenditure_setsu_id: 'setsu-12',
      code: '12',
      label: '委託料',
      valid_from_fiscal_year: 2020,
      valid_to_fiscal_year: null,
      legal_basis: EXPENDITURE_SETSU_LEGAL_BASIS,
    },
    {
      expenditure_setsu_id: 'setsu-07-2019',
      code: '07',
      label: '賃金',
      valid_from_fiscal_year: null,
      valid_to_fiscal_year: 2019,
      legal_basis: EXPENDITURE_SETSU_LEGAL_BASIS,
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
