/**
 * ホームページ。何をやっているかの説明とベータ告知、収録状況の入口。
 *
 * ⚠️ **収録状況は手で書かない。** `pipeline.json`（`report/budget/build.ts` の出力）を
 * 実行時に読んで出す。対象を広げた瞬間に文書だけが古くなる、という事故を避けるため
 * （AGENTS.md の「収録範囲を手で書くと嘘になる」原則）。
 *
 * ただし `pipeline.json` が読めなくても、この静的な説明部分は表示され続ける。
 * ホーム全体が真っ白になる方が、収録状況の1区画が欠けるより損害が大きい。
 */
import { useEffect, useState } from "react"
import { Layout } from "@/components/layout"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { loadPipeline, type Direction, type PipelineData } from "@/lib/pipeline"

const DIRECTION_JA: Record<Direction, string> = {
  expenditure: "歳出",
  revenue: "歳入",
}

export function HomePage() {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadPipeline()
      .then(setData)
      .catch((e: Error) => {
        // 生のエラー（JSON パース失敗など）はここでしか意味を持たない。
        // ホームは一般の利用者が最初に見る面なので、画面には行動が分かる文言だけを出す
        // （原因の追跡は console 経由。⚠️ /pipeline/ は逆で、見るのは報告を回している
        // 本人なので生のエラーをそのまま出す — ここだけの判断）。
        console.error("収録状況の読み込みに失敗しました:", e)
        setError("収録状況はいま表示できません。配布物そのものは")
      })
  }, [])

  return (
    <Layout>
      <main className="mx-auto flex max-w-3xl flex-col gap-10 px-4 py-16">
        <section className="flex flex-col gap-4">
          <h1 className="text-3xl font-semibold">fudoki（風土記）</h1>
          <p className="text-lg text-muted-foreground">
            公開されているのに読めない、を読める形にする。
          </p>
          <p className="leading-relaxed">
            自治体の予算は全部公開されている。ただし PDF か、自治体ごとに違う形の CSV である。
            ある市のある年度に「いじめ問題対策協議会関係費」がいくら付いたかを知るには、資料を開いて
            人が探すしかない。他市と比べるなら他市の資料も開き、科目体系の違いを人が頭の中で
            吸収することになる。年をまたぐ比較も、市をまたぐ比較も、事実上できない。
          </p>
          <p className="leading-relaxed">
            fudoki は日本の地方自治体の支出を<strong>事業単位（目）まで</strong>構造化し、
            国際標準の分類（COFOG）を割り当てて、外部データと join できる形で配布する。
            デジタル庁のダッシュボードは款・項レベルの目的別・性質別を既に出しているので、
            欠けているのは<strong>粒度</strong>（事業単位に届かない）と<strong>横断性</strong>
            （自治体ごとに個別形式で、同じ軸で並べられない）の2つだけで、そこだけを埋める。
          </p>
        </section>

        <Alert>
          <AlertTitle>ベータです</AlertTitle>
          <AlertDescription>
            URL・応答スキーマ・提供そのものを予告なく変更または停止することがあります。詳しくは
            {" "}
            <a className="underline" href="/terms/">
              ベータ利用条件
            </a>
            {" "}
            を確認してください。
          </AlertDescription>
        </Alert>

        <section className="flex flex-col gap-3">
          <h2 className="text-xl font-semibold">いま手に入るもの</h2>
          {error ? (
            <p className="text-sm text-muted-foreground">
              {error}
              {" "}
              <a
                className="underline"
                href="https://github.com/wwwyo/fudoki"
                target="_blank"
                rel="noreferrer"
              >
                GitHub
              </a>
              {" "}
              で直接確認できます。
            </p>
          ) : data ? (
            <div className="flex flex-wrap gap-3">
              {data.jurisdictions.map((j) => {
                const rows = (direction: Direction) =>
                  j.report.ingestion
                    .filter((p) => p.direction === direction)
                    .reduce((sum, p) => sum + p.rows, 0)
                const years = j.report.meta.fiscalYears
                return (
                  <Card key={j.code} className="min-w-[16rem] flex-1 gap-1 py-4">
                    <CardHeader className="px-4">
                      <CardTitle className="text-lg">
                        {j.report.meta.jurisdictionName}
                      </CardTitle>
                      <CardDescription>
                        {years.length > 2
                          ? `${years[0]}〜${years.at(-1)}年度`
                          : `${years.join("・")}年度`}
                        {/* 段階（当初予算／決算）。三鷹市は予算、狛江市は決算で性質が違うので、
                            年度だけ出すと数字の意味を取り違える */}
                        {" "}
                        {j.report.meta.phase.label}
                        {" "}
                        ・{" "}
                        {(["expenditure", "revenue"] as const)
                          .map((d) => `${DIRECTION_JA[d]} ${rows(d).toLocaleString("ja-JP")}行`)
                          .join("、")}
                      </CardDescription>
                    </CardHeader>
                  </Card>
                )
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">読み込み中…</p>
          )}
          <p className="text-sm text-muted-foreground">
            検証の中身は
            {" "}
            <a className="underline" href="/pipeline/">
              パイプライン報告
            </a>
            {" "}
            で確認できる。
          </p>
        </section>

        <section className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <a
            className="underline"
            href="https://docs.fudoki.dev/"
            target="_blank"
            rel="noreferrer"
          >
            API docs
          </a>
          <a
            className="underline"
            href="https://github.com/wwwyo/fudoki"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          <a className="underline" href="/pipeline/">
            パイプライン報告
          </a>
        </section>
      </main>
    </Layout>
  )
}
