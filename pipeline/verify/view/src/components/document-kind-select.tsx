/**
 * 原典の文書種別のセレクタ（ELT パイプラインの見出しで使う）。
 *
 * ⚠️ **選択肢は切り替えのためではなく、語彙（enum）を見せるためにある。**
 * 団体ごとに収録している文書は1種類なので、「当初予算」とだけ書くと
 * それが語彙の1要素ではなく暗黙の前提に見える。収録していない種類も
 * 選択肢に残し、disabled にする。
 */
import { DOCUMENT_KINDS, type DocumentKind } from '@/lib/pipeline'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function DocumentKindSelect({
  value,
  className,
  size,
}: {
  /** この団体が収録している文書種別 */
  value: DocumentKind
  className?: string
  size?: 'sm' | 'default'
}) {
  return (
    <Select
      items={DOCUMENT_KINDS.map((p) => ({ value: p.id, label: p.label }))}
      value={value}
    >
      <SelectTrigger aria-label="文書種別" className={className} size={size}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {DOCUMENT_KINDS.map((p) => (
            <SelectItem key={p.id} value={p.id} disabled={p.id !== value}>
              {p.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
