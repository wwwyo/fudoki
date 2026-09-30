import { STAGES, type Stage } from "@fudoki/report/common"
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  FileText,
  FolderOpen,
  GitMerge,
  Rows3,
  Scale,
  Table2,
} from "lucide-react"
import { useEffect } from "react"
import { Layout } from "@/components/layout"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { buttonVariants } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { PipelineData } from "@/lib/pipeline"
import { STAGE_JA } from "@/lib/verify"
import { withBase } from "@/lib/utils"

const stepDetails = {
  origin: {
    summary: "公開資料を選ぶ",
    format: "CSV / PDF",
    icon: FileText,
    description:
      "自治体が公開した予算・決算の CSV や PDF を対象にします。取得元と収録する年度を宣言し、その資料から読み取れる範囲を取り込みます。",
    path: "ingestion/budget/sources.toml",
  },
  ingestion: {
    summary: "資料から表を取り出す",
    format: "Parquet · 原典の単位",
    icon: Rows3,
    description:
      "CSV を表として読み込み、PDF は紙面の表から科目と金額を抽出します。原典の値と単位を保ったまま Parquet に保存し、取得 URL・日時・検査結果を証跡として残します。",
    path: "ingestion/budget/",
  },
  staging: {
    summary: "原典ごとに列名・型を整える",
    format: "原典と1対1 · 原典の単位",
    icon: Table2,
    description:
      "原典ごとに列名と型を整え、コードと名称を取り出します。行との1対1の対応と、原典の金額単位を保ちます。風土記では円への換算や団体をまたぐ統合は、後続の intermediate で行います。",
    path: "dbt/models/staging/budget/",
  },
  intermediate: {
    summary: "共通の構造へ統合・分類する",
    format: "円への換算 · 科目 · COFOG",
    icon: Scale,
    description:
      "提供用データを作るための中間処理です。団体間の構造を揃え、金額を円に換算し、共通科目への対応と COFOG（政府支出の機能別分類）を付与します。二重計上を避けるための会計間移転の消去対象も記録します。",
    path: "dbt/models/intermediate/budget/",
  },
  marts: {
    summary: "利用者向けの列・粒度を確定する",
    format: "提供用テーブル → CSV",
    icon: FolderOpen,
    description:
      "利用者が使う最終データモデルです。団体ごとに提供する列と粒度を確定し、この repo では CSV に書き出します。原典由来の金額と風土記の判断は別のリソースに分け、行の ID で結合できるようにします。CSV に列の定義・出典・利用条件を添える配布処理は dbt の外で行います。",
    path: "dbt/models/marts/budget/",
  },
} satisfies Record<
  Stage["id"],
  {
    summary: string
    format: string
    icon: typeof FileText
    description: string
    path: string
  }
>

function FlowArrow() {
  return (
    <div
      aria-hidden
      className="flex items-center justify-center text-muted-foreground"
    >
      <ArrowRight className="hidden size-5 md:block" />
      <ArrowDown className="size-5 md:hidden" />
    </div>
  )
}

function OverviewDiagram() {
  return (
    <figure
      aria-label="自治体の資料を風土記が構造化し、他の街や年と比較できるデータとして配布する"
      className="flex flex-col gap-4"
    >
      <div className="grid items-center gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
        <div className="flex flex-col gap-4">
          <p className="text-sm font-semibold">自治体が公開する資料</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "CSV", description: "公開データ" },
              { label: "PDF", description: "予算書・決算書" },
            ].map((document) => (
              <div
                key={document.label}
                className="flex flex-col gap-3 rounded-sm border bg-background p-4"
              >
                <FileText
                  aria-hidden
                  className="size-7 text-muted-foreground"
                />
                <div>
                  <p className="font-mono text-sm">{document.label}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {document.description}
                  </p>
                </div>
                <div aria-hidden className="flex flex-col gap-2">
                  <span className="h-px w-full bg-border" />
                  <span className="h-px w-3/4 bg-border" />
                  <span className="h-px w-full bg-border" />
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">
            団体ごとに形式・列名・単位が異なる
          </p>
        </div>
        <FlowArrow />
        <div className="flex flex-col items-center gap-4 rounded-sm border bg-muted/30 p-6">
          <div role="img" aria-label="風土記">
            <img
              src={`${import.meta.env.BASE_URL}logo.svg`}
              alt=""
              className="h-10 w-auto dark:hidden"
            />
            <img
              src={`${import.meta.env.BASE_URL}logo-dark.svg`}
              alt=""
              className="hidden h-10 w-auto dark:block"
            />
          </div>
          <div className="flex flex-col items-center gap-2 text-sm">
            <span>資料を集める</span>
            <ArrowDown aria-hidden className="size-4 text-muted-foreground" />
            <span>表の形を揃える</span>
            <ArrowDown aria-hidden className="size-4 text-muted-foreground" />
            <span>比較のための分類を加える</span>
          </div>
        </div>
        <FlowArrow />
        <div className="flex flex-col gap-4">
          <p className="text-sm font-semibold">同じ形のデータとして配布</p>
          <div className="overflow-hidden rounded-sm border bg-background">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">配布データの形の説明例</caption>
              <thead className="bg-muted/30">
                <tr>
                  <th className="p-3 font-medium">団体</th>
                  <th className="p-3 font-medium">年度</th>
                  <th className="p-3 font-medium">支出額</th>
                </tr>
              </thead>
              <tbody>
                {["A市", "B市"].map((city) => (
                  <tr key={city} className="border-t">
                    <td className="p-3">{city}</td>
                    <td className="p-3">…</td>
                    <td className="p-3">… 円</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="flex items-center gap-2 text-xs leading-relaxed text-muted-foreground">
            <GitMerge aria-hidden className="size-4 shrink-0" />
            他の街・他の年・外部データと比較
          </p>
        </div>
      </div>
      <figcaption className="text-xs leading-relaxed text-muted-foreground">
        概要図。表はデータの形を示す説明例です。比較するときは、予算の段階や会計の範囲も揃えます。
      </figcaption>
    </figure>
  )
}

function PipelineDiagram() {
  return (
    <figure
      aria-label="原典、取り込み、staging、intermediate、marts の順に処理し、marts の CSV に定義や出典を添えて配布する"
      className="flex flex-col gap-4"
    >
      <div className="grid gap-2 text-xs text-muted-foreground md:grid-cols-5">
        <p className="md:col-span-2">取得・取り込み（dbt の外）</p>
        <p className="md:col-span-3">dbt：staging → intermediate → marts</p>
      </div>
      <ol className="grid gap-8 md:grid-cols-5 md:gap-4">
        {STAGES.map((stage, index) => {
          const step = stepDetails[stage.id]
          const Icon = step.icon
          return (
            <li key={stage.id} className="relative flex">
              <a
                href={`#stage-${stage.id}`}
                className="flex w-full flex-col gap-3 rounded-sm border p-4 hover:bg-muted/30 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
              >
                <div className="flex items-center justify-between">
                  <Icon aria-hidden className="size-5" />
                  <span className="font-mono text-xs text-muted-foreground">
                    0{index + 1}
                  </span>
                </div>
                <p className="font-semibold">
                  {STAGE_JA[stage.id]}
                  <span className="mt-1 block text-xs font-normal text-muted-foreground">
                    （{stage.id}）
                  </span>
                </p>
                <p className="text-sm leading-relaxed">{step.summary}</p>
                <p className="mt-auto text-xs leading-relaxed text-muted-foreground">
                  {step.format}
                </p>
              </a>
              {index < STAGES.length - 1 && (
                <span
                  aria-hidden
                  className="absolute -bottom-6 left-1/2 -translate-x-1/2 text-muted-foreground md:top-1/2 md:-right-4 md:bottom-auto md:left-auto md:translate-x-1/2 md:-translate-y-1/2"
                >
                  <ArrowDown className="size-4 md:hidden" />
                  <ArrowRight className="hidden size-4 md:block" />
                </span>
              )}
            </li>
          )
        })}
      </ol>
      <div className="grid gap-4 md:grid-cols-5">
        <p className="border-t pt-3 text-xs leading-relaxed text-muted-foreground md:col-span-3">
          原典の値を保つ → 原典ごとに列名・型を整える
          <br />
          dbt の層は「準備 → 中間処理 → 利用者向けモデル」で分ける
        </p>
        <div className="flex flex-col gap-2 border-t border-dashed pt-3 md:col-span-2">
          <p className="flex items-center gap-2 text-sm">
            <ArrowUp aria-hidden className="size-4" />
            マスタ・対応表・分類規則
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            判断の根拠は repo の CSV に宣言し、intermediate で適用
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-3 rounded-sm border p-4">
        <p className="text-xs text-muted-foreground">配布処理（dbt の外）</p>
        <div className="grid items-center gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
          <p className="text-sm">marts が書き出した CSV</p>
          <FlowArrow />
          <div className="flex flex-col gap-2">
            <p className="text-sm font-semibold">
              定義・出典・利用条件を添える
            </p>
            <RepositoryLink path="fdp/build.py" />
          </div>
          <FlowArrow />
          <p className="text-sm font-semibold">配布物（Fiscal Data Package）</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-y py-3 text-xs leading-relaxed">
        <span>
          <strong className="font-semibold">証跡</strong>
          ：どの資料を、いつ、どう取り込んだか
        </span>
        <span>
          <strong className="font-semibold">検査</strong>
          ：行・金額・分類の整合性を各段で確かめる
        </span>
      </div>
      <figcaption className="text-xs leading-relaxed text-muted-foreground">
        各段を押すと詳しい説明へ移動します。これは役割を示す概念図です。原典由来の金額は
        staging から marts へ直接進み、分類などのデータは intermediate
        を経ます。自治体別の実際の依存関係は dbt の manifest から生成します。
      </figcaption>
    </figure>
  )
}

const concepts = [
  {
    name: "会計・款・項・目",
    description:
      "会計は一般会計・特別会計などの帳簿の区分です。一般会計では、款（教育費などの大分類）→ 項（小学校費などの内訳）→ 目の順に科目が細かくなります。科目コードや目の下の事業構造は団体ごとに異なるため、横断比較には対応表を使います。",
  },
  {
    name: "年度と予算の段階",
    description:
      "当初予算は年度の初めの計画、補正後の予算は変更後の計画、決算の支出額は実際に使った金額です。比較する年度と会計の範囲を明示し、当初予算同士・決算同士など、予算の段階を揃えます。歳入と歳出も区別します。",
  },
  {
    name: "マスタと対応表",
    description:
      "比較に使う科目の定義や、自治体の科目からその定義への対応は CSV で管理します。dbt seed で実行時の DuckDB テーブルに読み込み、変換から参照します。型は YAML、参照先や対応の重複はテストで確かめます。",
  },
  {
    name: "証跡と検査の範囲",
    description:
      "CSV は読み込んだ表から原文を復元して一致を確かめます。PDF は同じ検査ができないため、紙面の小計と内訳など、重複して印字された数字を照合します。検査が通った範囲と資料の注意点を、自治体別の画面で確認できます。",
  },
]

const repositoryGuide = [
  {
    purpose: "取得する資料と、自治体ごとの違いを知る",
    paths: ["ingestion/budget/sources.toml", "ingestion/budget/jurisdictions/"],
    description: "取得元・年度・PDF の組版の宣言と、原典の癖や実測の記録。",
  },
  {
    purpose: "列・階層・金額の読み方を確認する",
    paths: ["dbt/dbt_project.yml", "dbt/models/staging/budget/"],
    description: "団体ごとの階層、原典の列名、金額の単位と、その正規化。",
  },
  {
    purpose: "分類や科目の対応の根拠を読む",
    paths: ["dbt/seeds/budget/", "dbt/models/intermediate/budget/"],
    description:
      "科目マスタ・対応表・COFOG 規則の CSV と、それを適用する SQL。各宣言の basis に根拠を記録。",
  },
  {
    purpose: "どこまで検査しているかを確認する",
    paths: ["dbt/tests/"],
    description:
      "行や金額の保存、集計の一致、対応表の整合性などを確かめる SQL。",
  },
  {
    purpose: "配布データや画面の数字を辿る",
    paths: [
      "dbt/models/marts/budget/",
      "fdp/",
      "data/budget/datapackages/",
      "report/budget/",
      "apps/web/",
    ],
    description:
      "団体別の配布物、それを読む報告の生成処理、報告を表示する画面。",
  },
]

function RepositoryLink({ path }: { path: string }) {
  return (
    <a
      href={`https://github.com/wwwyo/fudoki/${path.endsWith("/") ? "tree" : "blob"}/main/${path}`}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline-offset-4 hover:underline"
    >
      <code className="text-xs break-all">{path}</code>
    </a>
  )
}

export function PipelineOverview({
  data,
  error,
}: {
  data: PipelineData | null
  error: string | null
}) {
  useEffect(() => {
    document.title = "収集のしくみと repo の読み方 | 風土記"
  }, [])

  return (
    <Layout>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 sm:px-8 sm:py-12">
        <header className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">風土記のパイプライン</p>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight sm:text-4xl">
            自治体の予算書を、
            <br />
            比べられるデータにする。
          </h1>
          <p className="max-w-3xl text-base leading-relaxed text-muted-foreground">
            風土記は、自治体が公開した予算・決算を事業単位の支出データに構造化するプロジェクトです。
            他の街や他の年と比較でき、数字から原典や判断の根拠を辿れる形で配布します。
          </p>
          <nav
            aria-label="このページの目次"
            className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-primary"
          >
            <a href="#summary" className="underline-offset-4 hover:underline">
              概要
            </a>
            <a
              href="#collection"
              className="underline-offset-4 hover:underline"
            >
              パイプラインの全体像
            </a>
            <a href="#concepts" className="underline-offset-4 hover:underline">
              共通の概念
            </a>
            <a
              href="#repository"
              className="underline-offset-4 hover:underline"
            >
              repo の読み方
            </a>
            <a href="#inspect" className="underline-offset-4 hover:underline">
              実データで確かめる
            </a>
          </nav>
        </header>
        <Separator />
        <section
          id="summary"
          aria-labelledby="summary-title"
          className="flex scroll-mt-20 flex-col gap-4"
        >
          <h2 id="summary-title" className="text-xl font-semibold">
            概要：何を集め、何を配るのか
          </h2>
          <OverviewDiagram />
        </section>
        <Separator />
        <section
          id="collection"
          aria-labelledby="collection-title"
          className="flex scroll-mt-20 flex-col gap-4"
        >
          <div className="flex flex-col gap-3">
            <h2 id="collection-title" className="text-xl font-semibold">
              パイプラインの全体像
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              どの自治体でも、各段の役割は共通です。資料の形式や帳簿の違いは、団体ごとの宣言で扱います。
            </p>
          </div>
          <PipelineDiagram />
        </section>
        <section
          aria-labelledby="example-title"
          className="flex flex-col gap-4"
        >
          <h2 id="example-title" className="text-lg font-semibold">
            例：原典別の整形から、提供用データまで
          </h2>
          <figure className="flex flex-col gap-3">
            <div className="grid items-center gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
              <div className="flex flex-col gap-2 border-l-2 pl-4">
                <p className="text-xs text-muted-foreground">
                  原典別の整形（staging）
                </p>
                <p className="font-mono text-lg">1,000 千円</p>
                <p className="text-sm">列名・型を整え、原典の単位は保つ</p>
              </div>
              <FlowArrow />
              <div className="flex flex-col gap-2 border-l-2 pl-4">
                <p className="text-xs text-muted-foreground">
                  統合・分類（intermediate）
                </p>
                <p className="font-mono text-lg">1,000,000 円</p>
                <p className="text-sm">円に換算し、共通科目・分類を付与</p>
              </div>
              <FlowArrow />
              <div className="flex flex-col gap-2 border-l-2 pl-4">
                <p className="text-xs text-muted-foreground">
                  提供用データ（marts）
                </p>
                <p className="font-mono text-lg">1,000,000 円</p>
                <p className="text-sm">金額と分類を別リソースの CSV にする</p>
              </div>
            </div>
            <figcaption className="text-xs leading-relaxed text-muted-foreground">
              説明用の例。正規化は処理の種類であり、staging
              の別名ではありません。原典由来の金額と判断は、配布物でも行の ID
              で結合できる別リソースにします。
            </figcaption>
          </figure>
        </section>
        <Separator />
        <section
          aria-labelledby="steps-title"
          className="grid gap-8 md:grid-cols-[220px_1fr]"
        >
          <h2 id="steps-title" className="text-xl font-semibold">
            各段で何をするか
          </h2>
          <ol className="flex flex-col gap-4">
            {STAGES.map((stage, index) => (
              <li
                id={`stage-${stage.id}`}
                key={stage.id}
                className="flex scroll-mt-20 flex-col gap-4"
              >
                <div className="grid grid-cols-[2rem_1fr] gap-3">
                  <span
                    aria-hidden
                    className="font-mono text-lg text-muted-foreground"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="flex flex-col gap-2">
                    <h3 className="font-semibold">
                      {STAGE_JA[stage.id]}（{stage.id}）
                    </h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {stepDetails[stage.id].description}
                    </p>
                    <RepositoryLink path={stepDetails[stage.id].path} />
                  </div>
                </div>
                {index < STAGES.length - 1 && <Separator />}
              </li>
            ))}
          </ol>
        </section>
        <Separator />
        <section
          id="concepts"
          aria-labelledby="concepts-title"
          className="flex scroll-mt-20 flex-col gap-4"
        >
          <h2 id="concepts-title" className="text-xl font-semibold">
            データを読むための共通の概念
          </h2>
          <dl className="grid gap-8 md:grid-cols-2">
            {concepts.map((concept) => (
              <div key={concept.name} className="flex flex-col gap-2">
                <dt className="font-semibold">{concept.name}</dt>
                <dd className="text-sm leading-relaxed text-muted-foreground">
                  {concept.description}
                </dd>
              </div>
            ))}
          </dl>
        </section>
        <Separator />
        <section
          id="repository"
          aria-labelledby="repository-title"
          className="flex scroll-mt-20 flex-col gap-4"
        >
          <div className="flex flex-col gap-3">
            <h2 id="repository-title" className="text-xl font-semibold">
              目的から repo を読む
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              原典・証跡・配布物と、分類の判断はリポジトリで管理します。 DuckDB
              は実行時に組む一時ファイルで、API
              と画面は配布物から生成する派生物です。 以下のリンクは GitHub の
              main ブランチを開きます。
            </p>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>確認したいこと</TableHead>
                <TableHead>読む場所</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {repositoryGuide.map((entry) => (
                <TableRow key={entry.purpose}>
                  <TableCell className="align-top">
                    <div className="flex min-w-48 flex-col gap-2 py-2">
                      <p>{entry.purpose}</p>
                      <p className="max-w-lg text-sm leading-relaxed whitespace-normal text-muted-foreground">
                        {entry.description}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-col gap-2 py-2">
                      {entry.paths.map((path) => (
                        <RepositoryLink key={path} path={path} />
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-sm leading-relaxed text-muted-foreground">
            全体の設計方針は <RepositoryLink path="docs/design-principles.md" />
            、予算の詳しい処理と追加手順は{" "}
            <RepositoryLink path="docs/budget-pipeline.md" /> にあります。
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            モデルの置き場は dbt の層名に揃えています。既存の SQL
            参照を壊さないため、モデル名の <code>core_*</code> と{" "}
            <code>pkg_*</code> は維持しています。変更の理由は{" "}
            <RepositoryLink path="docs/adr/0009-dbt-model-layers.md" />{" "}
            を参照してください。
          </p>
        </section>
        <Separator />
        <section
          id="inspect"
          aria-labelledby="inspect-title"
          className="flex scroll-mt-20 flex-col gap-4"
        >
          <div className="flex flex-col gap-3">
            <h2 id="inspect-title" className="text-xl font-semibold">
              自治体の実データで確かめる
            </h2>
            <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
              団体を選び、年度を指定します。系統図の線をクリックすると、その処理の入力と出力が下に並びます。
              表の行と PDF
              の紙面を照合し、検査結果・証跡・注意点を確認できます。
              図の依存関係は dbt の manifest.json から生成しています。
            </p>
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>
                自治体別の検証データを読み込めませんでした
              </AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : data ? (
            data.jurisdictions.length > 0 ? (
              <div className="flex flex-wrap gap-3">
                {data.jurisdictions.map((jurisdiction) => (
                  <a
                    key={jurisdiction.code}
                    href={withBase(`/pipeline/${jurisdiction.code}/`)}
                    className={buttonVariants({ variant: "outline" })}
                  >
                    {jurisdiction.report.meta.jurisdictionName}
                    <ArrowRight data-icon="inline-end" aria-hidden />
                  </a>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                収録済みの自治体はまだありません。
              </p>
            )
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              収録済みの自治体を読み込み中…
            </p>
          )}
          <div className="flex flex-col gap-3 text-sm leading-relaxed">
            <p>
              手元で資料の取得から配布物・報告まで作り直すには、repo のルートで{" "}
              <code className="font-mono">bun run pipeline</code>{" "}
              を実行します。画面を起動するには{" "}
              <code className="font-mono">bun run dev</code> を使います。
            </p>
            <p className="text-muted-foreground">
              初回のセットアップは <RepositoryLink path="README.md" />{" "}
              を参照してください。この検証画面はローカルの開発環境で利用します。
            </p>
          </div>
        </section>
      </main>
    </Layout>
  )
}
