/**
 * 年度セレクタ。ELT パイプライン・分析・明細の3画面から使う（切り替えた先の効果だけが違う）。
 *
 * 団体セレクタ（`JurisdictionSelect`）と違い、年度はどの画面でもローカル state で
 * 完結する（URL は変わらない）。だから遷移させず、選んだ値をそのまま呼び出し側へ返す。
 *
 * ⚠️ **収録年度が1つ以下のときに何を描くかは呼び出し側の判断**なので、ここでは扱わない
 * （`years.length <= 1` のときに Select を出すかどうかは呼び出し側で分岐する）。
 */
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

/**
 * 「全年度」の内部値。**年度と衝突しない文字列**にする
 * （Select は値を文字列で持つので、年度と同じ空間に入る）
 */
const ALL_YEARS = "all"

export function FiscalYearSelect({
  years,
  value,
  onChange,
  allowAll = false,
  className,
  size,
}: {
  years: number[]
  /** 選択中の年度。`allowAll` のとき null は「全年度」を表す */
  value: number | null
  onChange: (year: number | null) => void
  /** 「全年度」の選択肢を出すか（パイプライン画面だけが持つ） */
  allowAll?: boolean
  className?: string
  size?: "sm" | "default"
}) {
  return (
    <Select
      items={[
        ...(allowAll ? [{ value: ALL_YEARS, label: "全年度" }] : []),
        ...years.map((y) => ({ value: String(y), label: `${y}年度` })),
      ]}
      value={value === null ? ALL_YEARS : String(value)}
      onValueChange={(v) => onChange(v === ALL_YEARS ? null : Number(v))}
    >
      <SelectTrigger aria-label="年度" className={className} size={size}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {allowAll && <SelectItem value={ALL_YEARS}>全年度</SelectItem>}
          {years.map((y) => (
            <SelectItem key={y} value={String(y)}>
              {y}年度
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
