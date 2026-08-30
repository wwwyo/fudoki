/**
 * ホームページ。何をやっているかの説明とベータ告知、地図の入口。
 *
 * ⚠️ **地図は境界データが揃ってから別途作る。** ここにあるのは見出しだけの
 * プレースホルダで、`pipeline.json` はまだ読まない。地図は収録済み団体の塗り分けに
 * `pipeline.json` を使う予定だが、それは地図コンポーネント自身の実装時に足す話であって、
 * 使われる予定があるという理由だけで読み込みの仕組みを先取りして残すと、
 * 「呼んでいるのに何も出さない」という未使用コードになる（AGENTS.md:
 * 自分の変更で未使用になったものは片付ける）。
 */
import { useEffect, useState } from "react"
import { Layout } from "@/components/layout"
import { TokyoMap } from "@/components/tokyo-map"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { loadPipeline } from "@/lib/pipeline"

export function HomePage() {
  /**
   * 収録済みの団体コード。地図の塗り分けに使う。
   *
   * ⚠️ **手で列挙しない。** `pipeline.json` から取る。収録を増やした瞬間に
   * 画面だけが古くなる、という事故を避けるため（AGENTS.md）。
   *
   * ⚠️ 読めなくても地図は出す。62団体の境界は `tokyo.geojson` 側にあり、
   * `pipeline.json` が欠けて失われるのは「どこが埋まっているか」だけである。
   * 網羅範囲そのものを見せるのがこの地図の役割なので、全部を未収録として
   * 描くほうが、地図ごと消えるより伝わる。
   */
  const [recordedCodes, setRecordedCodes] = useState<ReadonlySet<string>>(new Set())

  useEffect(() => {
    loadPipeline()
      .then((d) => setRecordedCodes(new Set(d.jurisdictions.map((j) => j.code))))
      .catch((e: Error) => console.error("収録状況を読み込めませんでした", e))
  }, [])

  return (
    <Layout>
      <main className="mx-auto flex max-w-3xl flex-col gap-10 px-4 py-16">
        <section className="flex flex-col gap-4">
          {/*
            713年の官命で諸国へ同じ様式の報告を求め、集めたのが『風土記』
            （AGENTS.md 冒頭）。この墨絵はその由来そのもの（諸国から巻物を集めて
            役人が受け取る場面）を描いたもので、由来の説明を絵に肩代わりさせる。

            生成手段（commit した生成物には作り方を残す — AGENTS.md「スクリプト」節）:
              cwebp -q 80 fudoki-sumie.jpg -o hero.webp
            元は 1376×768 / 687KB の JPEG。q=80 で 56KB（目標 150KB 以下）。
            画像は横長で左側が余白なので、右詰めでトリミング表示する。
          */}
          <img
            src={`${import.meta.env.BASE_URL}hero.webp`}
            alt="713年の官命により諸国から集められた、地名の由来や産物を記した巻物を役人が受け取る場面を描いた墨絵"
            width={1376}
            height={768}
            className="h-auto w-full rounded-lg border object-cover object-right sm:max-h-56"
          />
          <h1 className="text-3xl font-semibold">風土記（fudoki）</h1>
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

        {/*
          ⚠️ alert.tsx 自体は変えない（shadcn CLI の更新で上書きされる）。
          既定の variant="default" は bg-card で Card と同じ背景になり、告知として
          見分けがつかない（ユーザー指摘）。ブランドカラー（青丹）の accent トークンと
          左ボーダーで、Card とは別物だと分かる見た目にする。accent はライト・ダーク
          両方で定義済みのトークンなので、ここで新しい色を足す必要はない。
        */}
        <Alert className="border-l-primary bg-accent text-accent-foreground border-l-4">
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
          <h2 className="text-xl font-semibold">収録状況</h2>
          <p className="text-muted-foreground text-sm">
            東京都の全区市町村（62団体）が最初の網羅範囲です。押すとその団体のパイプラインへ入ります。
          </p>
          <TokyoMap recordedCodes={recordedCodes} />
        </section>

        <section className="flex flex-wrap gap-2 text-sm">
          {/* ⚠️ `render` に `<a>` を渡すときは `nativeButton={false}` が要る。
              Base UI の既定は `nativeButton: true`（＝ネイティブの `<button>` が来る前提）で、
              指定を落とすとボタンのセマンティクスが外れたまま実行時に警告が出る。
              ここは見た目だけボタンの「リンク」なので、false が正しい。 */}
          <Button variant="outline" size="sm" nativeButton={false} render={
            <a href="https://docs.fudoki.dev/" target="_blank" rel="noreferrer">
              API docs
            </a>
          } />
          <Button variant="outline" size="sm" nativeButton={false} render={
            <a href="https://github.com/wwwyo/fudoki" target="_blank" rel="noreferrer">
              GitHub
            </a>
          } />
          <Button variant="outline" size="sm" nativeButton={false} render={<a href="/pipeline/">パイプライン報告</a>} />
        </section>
      </main>
    </Layout>
  )
}
