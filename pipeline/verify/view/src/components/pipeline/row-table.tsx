/**
 * 組の片側の行を出す表。
 *
 * 対応キー（source_row / ordinal）が反対側にもある行には番号バッジを付ける。
 * 行を押すと選択になり、反対側の同じ鍵の行が同じ見た目で点灯する。
 *
 * 決算の原典は数万行あるので、見えている窓だけを DOM に出す
 * （全行並べると描画が間に合わない）。
 */
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  forwardRef,
} from 'react'
import type { ColDoc, Direction } from '@/lib/pipeline'
import type { TableRows } from '@/lib/verify'
import { keysIntersect, rowKeySets } from '@/lib/verify'

const ROW_H = 24
const OVERSCAN = 12

export type RowTableHandle = {
  /** いずれかの鍵を持つ行が見える位置までスクロールする */
  scrollToKeys: (keys: Iterable<string>) => void
}

type Props = {
  table: TableRows
  /** 反対側にも同じ鍵がある行の集合（バッジを出す母数） */
  linkedKeys: Set<string> | null
  /** 選択中の行の鍵集合（両側で共有する。行は複数の鍵空間を持ちうる） */
  selectedKeys: Set<string> | null
  /** hover 中の行の鍵集合（反対側からの予告を受ける） */
  hoverKeys: Set<string> | null
  /**
   * 修飾キーに載せる向き。歳出・歳入を併せて見せる表示（overview）では
   * その表の向きを渡して `<空間>|<年度>|<向き>|<鍵>` に揃える。
   * `'row'` は行自身の direction 列で修飾する（向きが混ざる表用）。
   * 渡さないと向き修飾なし（1方向の表示）。
   */
  keyDir?: Direction | 'row'
  /** 列名 → 意味（ヘッダのツールチップ用。語彙が引けない表は空） */
  docs?: Record<string, ColDoc>
  onSelectRow: (keys: Set<string>) => void
  onHoverRow: (keys: Set<string> | null) => void
}

export const RowTable = forwardRef<RowTableHandle, Props>(function RowTable(
  {
    table,
    linkedKeys,
    selectedKeys,
    hoverKeys,
    keyDir,
    docs,
    onSelectRow,
    onHoverRow,
  },
  ref
) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewH, setViewH] = useState(400)

  // 対応・選択は修飾キー（`<空間>|<年度>|<鍵>`。両方向表示では `<空間>|<年度>|<向き>|<鍵>`）で比べる
  // — 空間・年度・向きをまたぐ誤対応を防ぐ。キー計算は verify 側で表ごとにキャッシュしてある
  const keySets = rowKeySets(table, keyDir)
  const keyIndex = useMemo(() => {
    const m = new Map<string, number>()
    keySets.forEach((ks, i) => {
      if (ks) for (const k of ks) if (!m.has(k)) m.set(k, i)
    })
    return m
  }, [keySets])

  useImperativeHandle(ref, () => ({
    scrollToKeys(keys: Iterable<string>) {
      const el = boxRef.current
      if (!el) return
      let i: number | undefined
      for (const k of keys) {
        i = keyIndex.get(k)
        if (i !== undefined) break
      }
      if (i === undefined) return
      const top = i * ROW_H
      if (top < el.scrollTop || top + ROW_H > el.scrollTop + el.clientHeight) {
        el.scrollTop = Math.max(0, top - el.clientHeight / 2)
        // バックグラウンドの頁では scroll イベントが遅れるため、仮想行の更新をイベントだけに任せない。
        setScrollTop(el.scrollTop)
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

  // 選択された行は窓の外にあることが多い。scrollToKey が内側の .rows を動かしても
  // その行が描画されるのは次の render なので、窓に現れたタイミングで
  // scrollIntoView して外側の .iowrap も寄せる
  // （内側だけだとパネル自体が画面外のままになる。毎 render ではなく選択ごと
  // 1回に留めないと、選択行が窓端に居るとき通常スクロールと取り合いになる）
  const pendingReveal = useRef(false)
  useEffect(() => {
    pendingReveal.current = selectedKeys !== null
  }, [selectedKeys])
  useEffect(() => {
    if (!pendingReveal.current) return
    const el = boxRef.current?.querySelector('tr.rowsel')
    if (!el) return
    el.scrollIntoView({ block: 'nearest' })
    pendingReveal.current = false
  })

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(
    table.rows.length,
    Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN
  )

  const ki = table.keyColumn ? table.columns.indexOf(table.keyColumn) : -1
  // 行番号系の鍵列（source_row など）は常に先頭に出す — 対応番号が表ごとに
  // 違う列に居ると見比べにくい。原典 CSV は source_row 列自体が無いので
  // 物理行番号の gutter（sr 鍵 ri+2 と同じ番号）を列として足す
  const implicit = !table.columns.includes('source_row') && !!table.provs
  const ordered =
    ki >= 0
      ? [
          table.keyColumn!,
          ...table.columns.filter((c) => c !== table.keyColumn),
        ]
      : table.columns
  const shown = ordered.slice(0, 14)
  const hidden = ordered.slice(14)
  const shownIdx = shown.map((c) => table.columns.indexOf(c))
  const colsN = shown.length + (implicit ? 1 : 0) + (hidden.length > 0 ? 1 : 0)

  return (
    // 高さに上限が要る — この div 自身がスクロールしないと仮想化の窓が動かない
    // （`.iowrap` が代わりにスクロールすると、画面外でも先頭窓のままになる）
    <div
      className="rows"
      ref={boxRef}
      onScroll={onScroll}
      style={{ maxHeight: 520 }}
    >
      {table.truncated && (
        <p
          className="text-xs"
          style={{ color: 'var(--muted-foreground)', margin: '0 0 4px' }}
        >
          ⚠️ 行が多すぎるため先頭 {table.rows.length.toLocaleString('ja-JP')}{' '}
          行だけを表示（打ち切り）
        </p>
      )}
      <table className="t">
        <thead>
          <tr>
            {implicit && <th className="mut">行</th>}
            {shown.map((c) => {
              const d = docs?.[c]
              const tip = d
                ? [d.title, d.description]
                    .filter(Boolean)
                    .join(' — ')
                    .replaceAll('**', '')
                : undefined
              return (
                <th key={c} title={tip}>
                  {c}
                </th>
              )
            })}
            {hidden.length > 0 && (
              <th title={`非表示の列: ${hidden.join('・')}`}>…</th>
            )}
          </tr>
        </thead>
        <tbody>
          {start > 0 && (
            <tr style={{ height: start * ROW_H }}>
              <td colSpan={colsN} />
            </tr>
          )}
          {table.rows.slice(start, end).map((r, i) => {
            const ri = start + i
            const ks = keySets[ri] ?? null
            const linked = keysIntersect(ks, linkedKeys)
            const sel = keysIntersect(ks, selectedKeys)
            const hov = keysIntersect(ks, hoverKeys)
            return (
              <tr
                key={ri}
                className={`${ks !== null ? 'rowhit' : ''}${sel ? ' rowsel' : ''}${hov ? ' rowhov' : ''}`}
                data-sr={ks ? [...ks].join('\n') : undefined}
                onClick={ks !== null ? () => onSelectRow(ks) : undefined}
                onMouseEnter={ks !== null ? () => onHoverRow(ks) : undefined}
                onMouseLeave={ks !== null ? () => onHoverRow(null) : undefined}
                style={{ height: ROW_H }}
              >
                {implicit && (
                  <td>
                    {linked ? <span className="srnum">{ri + 2}</span> : ri + 2}
                  </td>
                )}
                {shownIdx.map((ci) => {
                  const v = r[ci]
                  // 番号バッジは鍵列のセルに出す。鍵列を持たない表（COFOG 割当など）は
                  // 先頭セルの先頭に行番号を添える — バッジが無いと「対応がある行」が見えない
                  if (linked && !implicit && ci === ki)
                    return (
                      <td key={ci}>
                        <span className="srnum">{String(v ?? '')}</span>
                      </td>
                    )
                  if (linked && ki < 0 && !implicit && ci === shownIdx[0])
                    return (
                      <td key={ci}>
                        <span className="srnum">{ri + 1}</span>{' '}
                        {v == null ? '' : String(v)}
                      </td>
                    )
                  return <td key={ci}>{v == null ? '' : String(v)}</td>
                })}
                {hidden.length > 0 && (
                  <td
                    className="mut"
                    title={`非表示の列: ${hidden.join('・')}`}
                  >
                    …
                  </td>
                )}
              </tr>
            )
          })}
          {end < table.rows.length && (
            <tr style={{ height: (table.rows.length - end) * ROW_H }}>
              <td colSpan={colsN} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
})
