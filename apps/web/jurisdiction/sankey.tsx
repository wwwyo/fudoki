// 款→項の全体図。款・項それぞれの列で、ラベルが重ならない高さを確保してから帯を渡す。
import * as React from 'react'
import { formatYen, type Drill } from './types'

const BAR = 8
const KAN_SLOT = 30
const KOU_SLOT = 18
const KAN_GAP = 4
const KOU_GAP = 3

const amountText = (yen: number, missing?: boolean) => (missing ? '金額未記載' : formatYen(yen))

const fit = (values: number[], slot: number, gap: number, height: number) => {
  let low = 0
  let high = height
  for (let i = 0; i < 40; i++) {
    const mid = (low + high) / 2
    const used = values.reduce((sum, value) => sum + Math.max(value * mid, slot) + gap, 0)
    if (used > height) high = mid
    else low = mid
  }
  return low
}

const layout = (values: number[], scale: number, slot: number, gap: number) => {
  let top = 0
  return values.map((value) => {
    const height = Math.max(value * scale, 0)
    const size = Math.max(height, slot)
    const node = { top, size, y: top + (size - height) / 2, height }
    top += size + gap
    return node
  })
}

const ribbon = (xa: number, ya: number, ha: number, xb: number, yb: number, hb: number) => {
  const mid = (xa + xb) / 2
  return `M${xa} ${ya}C${mid} ${ya},${mid} ${yb},${xb} ${yb}L${xb} ${yb + hb}C${mid} ${yb + hb},${mid} ${ya + ha},${xa} ${ya + ha}Z`
}

export function Overview({ flows, height = 520 }: { flows: Drill[]; height?: number }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [width, setWidth] = React.useState(0)
  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(() => setWidth(el.clientWidth))
    observer.observe(el)
    setWidth(el.clientWidth)
    return () => observer.disconnect()
  }, [])
  const narrow = width < 560
  const left = narrow ? 104 : 180
  const right = narrow ? 170 : 260
  const kous = flows.flatMap((flow, kanIndex) => flow.kou.map((kou) => ({ kanIndex, kou })))
  const kanValues = flows.map((flow) => Math.max(0, flow.kan.yen))
  const kouValues = kous.map(({ kou }) => Math.max(0, kou.yen))
  const scale = Math.min(fit(kanValues, KAN_SLOT, KAN_GAP, height), fit(kouValues, KOU_SLOT, KOU_GAP, height))
  const kans = layout(kanValues, scale, KAN_SLOT, KAN_GAP)
  const kouNodes = layout(kouValues, scale, KOU_SLOT, KOU_GAP)
  const x0 = left
  const x1 = Math.max(width - right - BAR, x0 + BAR + 40)
  const cut = (name: string, n: number) => (narrow && Array.from(name).length > n ? `${Array.from(name).slice(0, n - 1).join('')}…` : name)
  const offsets = new Map<number, number>()
  const end = (nodes: { top: number; size: number }[]) => (nodes.length ? nodes[nodes.length - 1]!.top + nodes[nodes.length - 1]!.size : 0)
  const total = Math.max(end(kans), end(kouNodes), 40)
  return (
    <div ref={ref} className="w-full">
      {width ? (
        <svg width={width} height={total} role="img" aria-label="款から項への歳出の流れ" className="block font-sans">
          {kous.map(({ kanIndex, kou }, i) => {
            const source = kans[kanIndex]!
            const offset = offsets.get(kanIndex) ?? 0
            const h = kouNodes[i]!.height
            offsets.set(kanIndex, offset + h)
            if (h <= 0) return null
            return <path key={kou.id} d={ribbon(x0 + BAR, source.y + offset, h, x1, kouNodes[i]!.y, h)} className="fill-primary/20" />
          })}
          {flows.map((flow, i) => {
            const node = kans[i]!
            const label = cut(flow.kan.name, 9)
            return (
              <g key={flow.kan.id}>
                <title>{`${flow.kan.name} ${amountText(flow.kan.yen, flow.kan.amountMissing)}`}</title>
                <rect x={x0} y={node.y} width={BAR} height={Math.max(node.height, 2)} rx={2} className="fill-primary" />
                <text x={x0 - 8} y={node.top + node.size / 2 - 2} textAnchor="end" className="fill-foreground" fontSize={narrow ? 10.5 : 13}>{label}</text>
                <text x={x0 - 8} y={node.top + node.size / 2 + 12} textAnchor="end" className="fill-muted-foreground tabular-nums" fontSize={narrow ? 10 : 11.5}>{amountText(flow.kan.yen, flow.kan.amountMissing)}</text>
              </g>
            )
          })}
          {kous.map(({ kou }, i) => {
            const node = kouNodes[i]!
            return (
              <g key={kou.id}>
                <title>{`${kou.name} ${amountText(kou.yen, kou.amountMissing)}`}</title>
                <rect x={x1} y={node.y} width={BAR} height={Math.max(node.height, 2)} rx={2} className="fill-primary" />
                <text x={x1 + BAR + 8} y={node.top + node.size / 2 + 4} className="fill-foreground" fontSize={narrow ? 10.5 : 12}>
                  {cut(kou.name, 10)}
                  <tspan dx={6} className="fill-muted-foreground tabular-nums" fontSize={narrow ? 10 : 11}>{amountText(kou.yen, kou.amountMissing)}</tspan>
                </text>
              </g>
            )
          })}
        </svg>
      ) : null}
    </div>
  )
}
