import { expect, test } from 'bun:test'
import { buildCofogTree, type AggregateResponse } from './cofog-tree'
const versions = [
  { jurisdictionCode: '000001', versionId: 'v-' + 'a'.repeat(64) },
]
function result(
  groupBy: AggregateResponse['groupBy'],
  cells: AggregateResponse['cells']
): AggregateResponse {
  return {
    versions,
    datasets: [],
    groupBy,
    cells,
    totals: [],
    total: { amount: 100, lineCount: 4 },
  }
}
test('tree preserves SQL totals and shows the amounts that stop at division and group', () => {
  const division = result(
    ['cofog.division'],
    [
      { keys: ['04'], amount: 90, lineCount: 3 },
      { keys: ['unclassifiable'], amount: 10, lineCount: 1 },
    ]
  )
  const group = result(
    ['cofog.division', 'cofog.group'],
    [
      { keys: ['04', '04.5'], amount: 60, lineCount: 2 },
      { keys: ['04', 'not-descended'], amount: 30, lineCount: 1 },
    ]
  )
  const classification = result(
    ['cofog.division', 'cofog.group', 'cofog.class'],
    [
      { keys: ['04', '04.5', '04.5.1'], amount: 40, lineCount: 1 },
      { keys: ['04', '04.5', 'not-descended'], amount: 20, lineCount: 1 },
    ]
  )
  const tree = buildCofogTree(division, group, classification)
  expect(tree[0]?.sum).toBe(90)
  expect(tree[0]?.share).toBe(0.9)
  expect(tree[0]?.children?.[1]?.sum).toBe(30)
  expect(tree[0]?.children?.[1]?.filter).toBeNull()
  expect(tree[0]?.children?.[0]?.children?.[1]?.sum).toBe(20)
  expect(tree[1]?.filter).toBeNull()
  expect(tree[1]?.sum).toBe(10)
})
test('responses from different releases cannot form one tree', () => {
  const division = result(['cofog.division'], []),
    group = result(['cofog.division', 'cofog.group'], []),
    classification = result(
      ['cofog.division', 'cofog.group', 'cofog.class'],
      []
    )
  group.versions = [
    { jurisdictionCode: '000001', versionId: 'v-' + 'b'.repeat(64) },
  ]
  expect(() => buildCofogTree(division, group, classification)).toThrow(
    'versions or scope'
  )
})
