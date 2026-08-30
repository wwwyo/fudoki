/**
 * ベータ利用条件。
 *
 * ⚠️ **データのライセンスの要約はここに書かない。** 権利まわりの正本は
 * `data/LICENSE` で、AGENTS.md が「ここには要約も置かない」と決めている。
 * リンクと「原典ごとに条件が違う」という一文までに留める。
 */
import { Layout } from "@/components/layout"
import { Card, CardContent } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

export function TermsPage() {
  return (
    <Layout>
      <main className="mx-auto flex max-w-2xl flex-col gap-8 px-4 py-16 text-sm leading-relaxed">
        <h1 className="text-2xl font-semibold">ベータ利用条件</h1>

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">1. ベータである</h2>
          <p>
            fudoki（風土記）が配布する API・データセット・URL・応答スキーマは、いずれもベータの
            提供物である。予告なく変更または停止することがある。特定の URL やフィールドが今後も
            存在し続けることを前提に本番の仕組みを組まないこと。
          </p>
        </section>

        <Separator />

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">2. 無保証</h2>
          <p>
            配布しているデータは、自治体が公開した資料（CSV・PDF）から機械的に構造化したもので
            ある。正確性・完全性・最新性を保証しない。重要な判断に使う前に、配布物の{" "}
            <code>sources</code> から辿れる原典と必ず突き合わせること。
          </p>
        </section>

        <Separator />

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">3. 責任制限</h2>
          <p>
            fudoki のデータまたは API を利用したことによって生じた損害について、fudoki は責任を
            負わない。データの誤り、API の停止・変更、それらに起因する判断の誤りを含む。
          </p>
        </section>

        <Separator />

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">4. データのライセンス</h2>
          <p>
            データのライセンスは{" "}
            <a
              className="underline"
              href="https://github.com/wwwyo/fudoki/blob/main/data/LICENSE"
              target="_blank"
              rel="noreferrer"
            >
              data/LICENSE
            </a>{" "}
            に従う。原典ごとに条件が違うため、要約はここに書かない。利用の前に必ず参照すること。
          </p>
        </section>

        <Separator />

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">5. API について</h2>
          <p>fudoki は API に対して次の権限を持つ。</p>
          <Card>
            <CardContent>
              <ul className="list-disc pl-5">
                <li>API キーの発行と失効</li>
                <li>レート制限</li>
                <li>アクセスログの取得</li>
                <li>提供の停止</li>
              </ul>
            </CardContent>
          </Card>
          <p>
            API キーは<strong>任意</strong>である。キーが無くても API を利用できるが、レートは
            低く抑える。キーを取得すると制限が緩和される。API を使えるかどうかを鍵で握る形には
            しない。
          </p>
          <p>
            配布物の正本は GitHub リポジトリであり、API はそこから生成した派生物である。
            API が止まっても、正本は repo に残る。
          </p>
        </section>

        <Separator />

        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">6. 法的な最終判断</h2>
          <p>
            本条件および data/LICENSE の記載は fudoki の判断であり、法的助言ではない。
            商用利用や再配布など、権利関係の最終的な判断が必要な場面では専門家に確認すること。
          </p>
        </section>
      </main>
    </Layout>
  )
}
