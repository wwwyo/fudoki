import type { apiClient } from './api-client'
import { cofogLabel } from '@fudoki/fiscal/detail'
import { share, type CofogTreeNode } from '@fudoki/fiscal/cofog'
export type {
  CofogTreeFilter as CofogNodeFilter,
  CofogTreeNode,
} from '@fudoki/fiscal/cofog'
import { STATUS_JA } from './display'

export type AggregateResponse = Awaited<
  ReturnType<typeof apiClient.aggregateFiscalDatasets>
>
const versionKey = (response: AggregateResponse) =>
  response.versions
    .map((v) => `${v.jurisdictionCode}:${v.versionId}`)
    .sort()
    .join('|')

export function buildCofogTree(
  division: AggregateResponse,
  group: AggregateResponse,
  classification: AggregateResponse
): CofogTreeNode[] {
  if (
    versionKey(division) !== versionKey(group) ||
    versionKey(division) !== versionKey(classification) ||
    !division.total
  )
    throw new Error('COFOG responses differ in release or scope')
  const total = division.total.amount
  function node(
    cell: AggregateResponse['cells'][number],
    depth: CofogTreeNode['depth']
  ): CofogTreeNode {
    const code = cell.keys.at(-1)!,
      assigned = /^\d{2}(\.\d+)*$/.test(code)
    return {
      key: cell.keys.join(':'),
      code: assigned ? code : '',
      label: assigned
        ? cofogLabel(depth, code)
        : (STATUS_JA[code] ??
          (code === 'not-descended'
            ? 'この分類の深さまで分類していない'
            : code)),
      depth,
      count: cell.lineCount,
      sum: cell.amount,
      share: share(cell.amount, total),
      filter: assigned
        ? {
            division: cell.keys[0]!,
            ...(depth !== 'division' ? { group: cell.keys[1] } : {}),
            ...(depth === 'class' ? { class: cell.keys[2] } : {}),
          }
        : null,
    }
  }
  return division.cells.map((cell) => {
    const parent = node(cell, 'division')
    if (parent.filter)
      parent.children = group.cells
        .filter((g) => g.keys[0] === cell.keys[0])
        .map((g) => {
          const child = node(g, 'group')
          if (child.filter)
            child.children = classification.cells
              .filter((c) => c.keys[0] === g.keys[0] && c.keys[1] === g.keys[1])
              .map((c) => node(c, 'class'))
          return child
        })
    return parent
  })
}
