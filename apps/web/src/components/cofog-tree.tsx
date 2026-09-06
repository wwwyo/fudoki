/**
 * COFOG のツリー表示（大分類 → 中分類 → 小分類）。
 *
 * ⚠️ **どこまで降りているかが見えること。** 大分類止まりの行は「（大分類までで
 * 止まった分）」という葉ノードとして出し、割合の高さを合否に使わない
 * （cofog-panel.tsx が同じ理由を説明している）。この葉ノードは選択できない
 * （API の filter は division/group/class の完全一致しか無く、
 * 「そこで止まった行だけ」を絞る術が無いため）。
 *
 * ⚠️ **選んだ行の明細は、その行の直下にインラインで挟む。** ツリーの下に独立した
 * セクションを置くと、縦に長いツリーでは選んだ行と明細が同時に見えなくなる
 * （AGENTS.md タスク3）。展開（chevron）と選択（行クリック）は別の操作なので、
 * 「開いている」ことと「選ばれている」ことは別の状態として扱う。
 */
import { useState } from "react"
import { ChevronRight } from "lucide-react"
import { DIVISION_COLOR, pct, senYen, count } from "@/lib/pipeline"
import type { CofogNodeFilter, CofogTreeNode } from "@/lib/cofog-tree"
import { cn } from "@/lib/utils"

export function CofogTree({
  nodes,
  selected,
  onSelect,
  renderDetail,
}: {
  nodes: CofogTreeNode[]
  selected: CofogNodeFilter | null
  onSelect: (filter: CofogNodeFilter) => void
  /** 選択中の行の直下に出す明細。呼び出し側（analysis.tsx）が API 呼び出しの詳細を持つ */
  renderDetail: (filter: CofogNodeFilter) => React.ReactNode
}) {
  return (
    <div className="flex flex-col rounded-lg border text-sm">
      {/* ⚠️ 金額の単位はここで1回だけ明示する。行ごとに「千円」を繰り返すと
          ノイズになるが、書かないと明細（円）と混同する（AGENTS.md の指摘）。 */}
      <div className="flex items-center gap-2 border-b bg-muted/30 px-2 py-1 text-xs text-muted-foreground">
        <span className="ml-auto shrink-0 whitespace-nowrap text-right">金額（千円）・構成比・件数</span>
      </div>
      {nodes.map((n) => (
        <TreeRow key={n.key} node={n} depth={0} selected={selected} onSelect={onSelect} renderDetail={renderDetail} />
      ))}
    </div>
  )
}

/** 選択中のノードをハイライトするための filter 一致判定。exported for testing */
export const sameFilter = (a: CofogNodeFilter | null, b: CofogNodeFilter | null) =>
  a !== null && b !== null && a.division === b.division && a.group === b.group && a.class === b.class

function TreeRow({
  node,
  depth,
  selected,
  onSelect,
  renderDetail,
}: {
  node: CofogTreeNode
  depth: number
  selected: CofogNodeFilter | null
  onSelect: (filter: CofogNodeFilter) => void
  renderDetail: (filter: CofogNodeFilter) => React.ReactNode
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
        onKeyDown={
          node.filter
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onSelect(node.filter!)
                }
              }
            : undefined
        }
        tabIndex={node.filter ? 0 : undefined}
        role={node.filter ? "button" : undefined}
        aria-pressed={node.filter ? isSelected : undefined}
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
          {senYen(node.sum)} ・ {pct(node.share)} ・ {count(node.count)}件
        </span>
      </div>
      {isSelected && node.filter && (
        // ⚠️ 明細は表なので、ツリーの字下げ（depth * 20px）をそのまま当てると
        // 深い階層（小分類）で横幅が潰れる。字下げは行のラベル位置に揃える程度に留め、
        // 表自体は overflow-x-auto で横スクロールに逃がす（cofog-statement.tsx 側）。
        <div
          className="border-t bg-muted/20 py-2 pr-2"
          style={{ paddingLeft: `${Math.min(depth, 1) * 20 + 8}px` }}
        >
          {renderDetail(node.filter)}
        </div>
      )}
      {open && node.children?.map((c) => (
        <TreeRow key={c.key} node={c} depth={depth + 1} selected={selected} onSelect={onSelect} renderDetail={renderDetail} />
      ))}
    </div>
  )
}
