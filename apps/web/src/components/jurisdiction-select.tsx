/**
 * 団体セレクタ。ELT パイプラインと分析の両方から使う（行き先だけが違う）。
 *
 * ⚠️ **団体が1つ以下のときに何を描くかは呼び出し側の判断**なので、ここでは扱わない。
 * パイプラインは見出しが既に団体名を言っているので何も出さないが、分析は出す。
 * 片方へ寄せると、寄せなかった側の画面から団体名が消えるか二重になる。
 */
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { withBase } from "@/lib/utils"

export type JurisdictionOption = { code: string; name: string }

export function JurisdictionSelect({
  jurisdictions,
  value,
  basePath,
  placeholder,
}: {
  jurisdictions: JurisdictionOption[]
  /** 選択中の団体コード。まだ団体を見ていない画面（未収録ページ）では渡さない */
  value?: string
  basePath: "pipeline" | "analysis"
  placeholder?: string
}) {
  return (
    <Select
      items={jurisdictions.map((j) => ({ value: j.code, label: j.name }))}
      value={value}
      onValueChange={(v) => {
        // state だけ変えると URL が古い団体のままになる（地図からの遷移・
        // ブックマーク・共有リンクがすべて「見ている団体」を表さなくなる）。
        window.location.href = withBase(`/${basePath}/${v}/`)
      }}
    >
      <SelectTrigger aria-label="団体">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {jurisdictions.map((j) => (
            <SelectItem key={j.code} value={j.code}>
              {j.name}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
