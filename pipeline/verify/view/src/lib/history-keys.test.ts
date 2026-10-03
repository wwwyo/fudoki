import { expect, test } from 'bun:test'
import { rowKeySets, edgeDir } from './verify'
import type { TableRows } from './verify'

test('同年度・同方向・同じ行番号の補正を別版・別表と誤対応させない', () => {
  const raw: TableRows = { kind: 'table', keyColumn: 'source_row', totalRows: 3, columns: ['year','direction','edition','resource','source_row','fund_code','kan_code','kou_code','moku_code'], rows: [
    [2023,'expenditure','a','expenditure-detail',1,'1','7','1','2'],
    [2023,'expenditure','b','expenditure-detail',1,'1','7','1','2'],
    [2023,'expenditure','a','approval-1',1,null,null,null,null],
  ] }
  const keys = rowKeySets(raw,'row')
  expect([...keys[0]!].filter(k => keys[1]!.has(k))).toEqual([])
  expect([...keys[0]!].filter(k => keys[2]!.has(k))).toEqual([])
  const stg: TableRows = {kind:'table', keyColumn:'source_row', totalRows:1, columns:['fiscal_year','direction','dataset_id','source_row'],rows:[[2023,'expenditure','132195:2023:expenditure:supplementary:a:expenditure-detail',1]]}
  expect([...rowKeySets(stg,'row')[0]!]).toEqual([...keys[0]!])
  const changes: TableRows = {kind:'table', keyColumn:'source_row', totalRows:2, columns:['dataset_id','source_row','budget_item_id'],rows:[['132195:2023:expenditure:supplementary:a:expenditure-detail',1,'same-target'],['132195:2023:expenditure:supplementary:b:expenditure-detail',1,'same-target']]}
  const changesKeys = rowKeySets(changes,'row')
  expect([...changesKeys[0]!]).toEqual([...keys[0]!])
  expect([...changesKeys[0]!].filter(k=>changesKeys[1]!.has(k))).toEqual([])
})

test('歳出履歴PDFの辺は行・hitの両側を歳出として修飾する',()=>{ expect(edgeDir('source.fudoki.raw_132195.doc_sha.origin','source.fudoki.raw_132195_history.data')).toBe('expenditure') })
