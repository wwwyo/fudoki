/**
 * まだ収録していない団体のページ。ELT パイプラインと分析で行き先だけが違う。
 * 地図は62団体すべてを押せるので、収録済みかどうかに関わらずページが要る。
 */
import { JurisdictionSelect, type JurisdictionOption } from "@/components/jurisdiction-select"
import { Layout } from "@/components/layout"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function NotCollectedPage({
  code,
  name,
  jurisdictions,
  basePath,
}: {
  code: string
  name?: string
  jurisdictions: JurisdictionOption[]
  basePath: "pipeline" | "analysis"
}) {
  return (
    <Layout>
      <main className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
        <h1 className="text-xl font-semibold">{name ?? code}</h1>
        <Alert>
          <AlertTitle>この団体はまだ収録していません</AlertTitle>
          <AlertDescription>
            {name ?? code}（団体コード {code}）の予算データは、まだ fudoki のパイプラインを通していません。
          </AlertDescription>
        </Alert>
        {jurisdictions.length > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">収録済みの団体を見る:</span>
            <JurisdictionSelect jurisdictions={jurisdictions} basePath={basePath} placeholder="団体を選ぶ" />
          </div>
        )}
      </main>
    </Layout>
  )
}
