/**
 * COFOG のツリー表示（大分類 → 中分類 → 小分類）。
 *
 * ⚠️ **どこまで降りているかが見えること。** 大分類止まりの行は「（大分類までで
 * 止まった分）」という葉ノードとして出し、割合の高さを合否に使わない
 * （cofog-panel.tsx が同じ理由を説明している）。この葉ノードは選択できない
 * （API の filter は division/group/class の完全一致しか無く、
 * 「そこで止まった行だけ」を絞る術が無いため）。
 */
import { useState } from "react"
import { ChevronRight } from "lucide-react"
import { DIVISION_COLOR, pct, yen } from "@/lib/pipeline"
import type { CofogNodeFilter, CofogTreeNode } from "@/lib/cofog-tree"
import { cn } from "@/lib/utils"

export function CofogTree({
  nodes,
  total,
  selected,
  onSelect,
}: {
  nodes: CofogTreeNode[]
  /** 割合の分母（合計、未分類込み）。cofog.total.sum を渡す */
  total: number
  selected: CofogNodeFilter | null
  onSelect: (filter: CofogNodeFilter) => void
}) {
  return (
    <div className="flex flex-col rounded-lg border text-sm">
      {nodes.map((n) => (
        <TreeRow key={n.key} node={n} depth={0} total={total} selected={selected} onSelect={onSelect} />
      ))}
    </div>
  )
}

const sameFilter = (a: CofogNodeFilter | null, b: CofogNodeFilter | null) =>
  a !== null && b !== null && a.division === b.division && a.group === b.group && a.class === b.class

function TreeRow({
  node,
  depth,
  total,
  selected,
  onSelect,
}: {
  node: CofogTreeNode
  depth: number
  total: number
  selected: CofogNodeFilter | null
  onSelect: (filter: CofogNodeFilter) => void
}) {
  const [open, setOpen] = useState(depth === 0)
  const hasChildren = (node.children?.length ?? 0) > 0
  const isSelected = sameFilter(node.filter, selected)
  const divisionColor = DIVISION_COLOR[node.code.slice(0, 2)] ?? DIVISION_COLOR[node.key.slice(0, 2)]

  return (
    <div className="border-t first:border-t-0">
      <div
        className={cn(
          "flex items-center gap-2 px-2 py-1.5",
          node.filter && "cursor-pointer hover:bg-muted/50",
          isSelected && "bg-muted",
        )}
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
        onClick={node.filter ? () => onSelect(node.filter!) : undefined}
        role={node.filter ? "button" : undefined}
      >
        <button
          type="button"
          aria-label={hasChildren ? (open ? "折りたたむ" : "展開する") : undefined}
          className={cn("shrink-0 rounded p-0.5 hover:bg-muted", !hasChildren && "invisible")}
          onClick={(e) => {
            e.stopPropagation()
            setOpen((v) => !v)
          }}
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        {node.depth === "division" && (
          <i aria-hidden className="size-2.5 shrink-0 rounded-sm" style={{ background: divisionColor }} />
        )}
        <span className={cn("shrink-0 font-medium tabular-nums", node.code === "" && "text-muted-foreground")}>
          {node.code || "—"}
        </span>
        <span className={cn("truncate", node.code === "" && "text-xs text-muted-foreground")}>{node.label}</span>
        <span className="ml-auto shrink-0 whitespace-nowrap text-right text-xs text-muted-foreground tabular-nums">
          {yen(node.sum)}円 ・ {pct(total > 0 ? node.sum / total : 0)} ・ {yen(node.count)}件
        </span>
      </div>
      {open && node.children?.map((c) => (
        <TreeRow key={c.key} node={c} depth={depth + 1} total={total} selected={selected} onSelect={onSelect} />
      ))}
    </div>
  )
}
