/**
 * COFOG のディビジョン表示。
 *
 * **色は識別の補助で、コードは必ず文字でも出す** — 色だけだと色覚特性のある読者と
 * 読み上げに届かない。COFOG パネルと明細の両方から使うので共有する。
 */
import { DIVISION_COLOR } from '@/lib/pipeline'

export function Division({ code, label }: { code: string; label?: string }) {
  if (!code) return <span className="text-muted-foreground">—</span>
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <i aria-hidden className="size-2.5 shrink-0 rounded-sm" style={{ background: DIVISION_COLOR[code] }} />
      <span className="font-medium">{code}</span>
      {label && <span className="text-muted-foreground">{label}</span>}
    </span>
  )
}

/**
 * COFOG のコードの連なり（`04 経済業務 › 04.5 運輸 › 04.5.1 道路交通`）。
 *
 * ⚠️ **group / class が空でも「—」や「その他」を出さない。**
 * 空は「該当が無い」ではなく**まだ降りていない**ことを意味するので、
 * 無い段は描かない（読者に欠落として見せない）。
 * どこまで降りているかは「到達粒度」の節が母数つきで語る。
 */
export function CofogChain(
  { division, divisionLabel, group, groupLabel, cls, clsLabel }: {
    division: string; divisionLabel: string
    group: string; groupLabel: string
    cls: string; clsLabel: string
  },
) {
  if (!division) return <span className="text-muted-foreground">—</span>
  const deeper = [
    [group, groupLabel] as const,
    [cls, clsLabel] as const,
  ].filter(([code]) => code)
  return (
    <span className="inline-flex flex-col gap-0.5">
      <Division code={division} label={divisionLabel} />
      {deeper.map(([code, label]) => (
        <span key={code} className="whitespace-nowrap pl-4 text-xs text-muted-foreground">
          <span aria-hidden>↳ </span>
          <span className="font-medium text-foreground">{code}</span> {label}
        </span>
      ))}
    </span>
  )
}
