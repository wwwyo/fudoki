/**
 * ホームページ。何をやっているかの説明とベータ告知、地図の入口。
 *
 * ⚠️ **地図に収録状況を持ち込まない。** 62団体すべてを同じ扱いで押せるようにし、
 * どこが埋まっているかは各団体のページ側が告げる。ホームで塗り分けると
 * `pipeline.json` を読む必要が生まれ、報告の生成物が欠けただけで
 * 入口が壊れる（実際に古い pipeline.json を掴んで塗り分けが全部外れた）。
 */
import { Layout } from "@/components/layout"
import { TokyoMap } from "@/components/tokyo-map"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Info } from "lucide-react"
import { withBase } from "@/lib/utils"

export function HomePage() {
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
          <p className="text-lg leading-relaxed text-muted-foreground">
            あなたの街の家計簿をオープンに。
          </p>
          <p className="leading-relaxed">
            <strong>公開されているのに読めない。</strong>自治体の予算は PDF か、
            自治体ごとに違う形の CSV で出ている。ある市のある年度に
            「いじめ問題対策協議会関係費」がいくら付いたかを知るには、資料を開いて人が探すしかない。
            他市と比べるなら他市の資料も開き、科目体系の違いを人が頭の中で吸収することになる。
            年をまたぐ比較も、市をまたぐ比較も、事実上できない。
          </p>
          <p className="leading-relaxed">
            fudoki は日本の地方自治体の支出を<strong>事業単位まで</strong>構造化し、
            COFOG を割り当てて、外部データと join できる形で配布する。
            デジタル庁のダッシュボードが目的別と性質別まで出している以上、
            欠けているのは粒度と横断性の2つだけで、そこだけを埋める。
          </p>
        </section>

        {/*
          ⚠️ className で見た目を足さない。Card と同じ背景に見えるのは Alert の
          既定 variant の仕様で、変えるならデザインシステム側（alert.tsx の variant）
          の仕事である。利用側で bg や border を上書きすると、shadcn の variant を
          迂回した独自スタイルが1箇所だけ生まれる。
        */}
        <Alert>
          <Info aria-hidden />
          <AlertTitle>ベータです</AlertTitle>
          <AlertDescription>
            URL・応答スキーマ・提供そのものを予告なく変更または停止することがあります。詳しくは
            {" "}
            <a className="underline" href={withBase("/terms/")}>
              ベータ利用条件
            </a>
            {" "}
            を確認してください。
          </AlertDescription>
        </Alert>

        <section className="flex flex-col gap-3">
          <h2 className="text-xl font-semibold">東京都の区市町村</h2>
          <TokyoMap />
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
          <Button variant="outline" size="sm" nativeButton={false} render={<a href={withBase("/pipeline/")}>パイプライン報告</a>} />
        </section>
      </main>
    </Layout>
  )
}
