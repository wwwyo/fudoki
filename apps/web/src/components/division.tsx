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
