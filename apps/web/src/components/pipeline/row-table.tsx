/**
 * 組の片側の行を出す表。
 *
 * 対応キー（source_row / ordinal）が反対側にもある行には番号バッジを付ける。
 * 行を押すと選択になり、反対側の同じ鍵の行が同じ見た目で点灯する。
 *
 * 決算の原典は数万行あるので、見えている窓だけを DOM に出す
 * （全行並べると描画が間に合わない）。
 */
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from "react"
import type { TableRows } from "@/lib/verify"
import { linkKey } from "@/lib/verify"

const ROW_H = 24
const OVERSCAN = 12

export type RowTableHandle = {
  /** その鍵の行が見える位置までスクロールする */
  scrollToKey: (key: string) => void
}

type Props = {
  table: TableRows
  /** 反対側にも同じ鍵がある行の集合（バッジを出す母数） */
  linkedKeys: Set<string> | null
  /** 選択中の行キー（両側で共有する） */
  selectedKey: string | null
  /** hover 中の行キー（反対側からの予告を受ける） */
  hoverKey: string | null
  onSelectRow: (key: string, row: unknown[]) => void
  onHoverRow: (key: string | null) => void
}

export const RowTable = forwardRef<RowTableHandle, Props>(function RowTable(
  { table, linkedKeys, selectedKey, hoverKey, onSelectRow, onHoverRow },
  ref,
) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewH, setViewH] = useState(400)

  // 対応・選択は修飾キー（`<年度>|<鍵>`）で比べる — 年度をまたぐ誤対応を防ぐ
  const keys = useMemo(() => table.rows.map((r) => linkKey(table, r)), [table])
  const keyIndex = useMemo(() => {
    const m = new Map<string, number>()
    keys.forEach((k, i) => {
      if (k !== null && !m.has(k)) m.set(k, i)
    })
    return m
  }, [keys])

  useImperativeHandle(ref, () => ({
    scrollToKey(key: string) {
      const i = keyIndex.get(key)
      const el = boxRef.current
      if (i === undefined || !el) return
      const top = i * ROW_H
      if (top < el.scrollTop || top + ROW_H > el.scrollTop + el.clientHeight) {
        el.scrollTop = Math.max(0, top - el.clientHeight / 2)
      }
    },
  }))

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewH(el.clientHeight))
    ro.observe(el)
    setViewH(el.clientHeight)
    return () => ro.disconnect()
  }, [])

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(table.rows.length, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN)

  const ki = table.keyColumn ? table.columns.indexOf(table.keyColumn) : -1
  const shownIdx = table.columns.slice(0, 14).map((c) => table.columns.indexOf(c))
  const shown = shownIdx.map((i) => table.columns[i]!)

  return (
    // 高さに上限が要る — この div 自身がスクロールしないと仮想化の窓が動かない
    // （`.iowrap` が代わりにスクロールすると、画面外でも先頭窓のままになる）
    <div className="rows" ref={boxRef} onScroll={onScroll} style={{ maxHeight: 520 }}>
      <table className="t">
        <thead>
          <tr>
            {shown.map((c) => (
              <th key={c}>{c}</th>
            ))}
            {table.columns.length > 14 && <th>…</th>}
          </tr>
        </thead>
        <tbody>
          {start > 0 && (
            <tr style={{ height: start * ROW_H }}>
              <td colSpan={shown.length + 1} />
            </tr>
          )}
          {table.rows.slice(start, end).map((r, i) => {
            const ri = start + i
            const k = keys[ri]
            const linked = k !== null && linkedKeys !== null && linkedKeys.has(k)
            const sel = k !== null && k === selectedKey
            const hov = k !== null && k === hoverKey
            return (
              <tr
                key={ri}
                className={`${k !== null ? "rowhit" : ""}${sel ? " rowsel" : ""}${hov ? " rowhov" : ""}`}
                data-sr={k ?? undefined}
                data-rowsel={sel || undefined}
                onClick={k !== null ? () => onSelectRow(k, r) : undefined}
                onMouseEnter={k !== null ? () => onHoverRow(k) : undefined}
                onMouseLeave={k !== null ? () => onHoverRow(null) : undefined}
                style={{ height: ROW_H }}
              >
                {shownIdx.map((ci) => {
                  const v = r[ci]
                  return (
                    <td key={ci}>
                      {linked && ci === ki ? (
                        <span className="srnum">{String(v ?? "")}</span>
                      ) : v == null ? (
                        ""
                      ) : (
                        String(v)
                      )}
                    </td>
                  )
                })}
                {table.columns.length > 14 && <td className="mut">…</td>}
              </tr>
            )
          })}
          {end < table.rows.length && (
            <tr style={{ height: (table.rows.length - end) * ROW_H }}>
              <td colSpan={shown.length + 1} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
})
