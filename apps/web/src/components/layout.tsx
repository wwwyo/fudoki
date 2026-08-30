/**
 * 3ページ（/ ・ /pipeline/ ・ /terms/、将来 /analysis/）に共通する外枠。
 *
 * Vite の MPA なので、ページ間の遷移は素の `<a>` によるフルロードになる
 * （React Router は入れない）。ThemeProvider / TooltipProvider もここで1回だけ張る。
 */
import type { ReactNode } from "react"
import { ThemeProvider } from "@/components/theme-provider"
import { TooltipProvider } from "@/components/ui/tooltip"

/**
 * `external` は別サイト（docs.fudoki.dev）への導線。新しいタブで開く。
 * ⚠️ 並びは「ホーム → パイプライン → API docs → 利用条件」で固定する。
 * API docs だけを右端へ寄せると、外部サイトであることより先に
 * 「他とは別格の項目」に見えてしまう。
 */
const NAV = [
  { href: "/", label: "ホーム" },
  { href: "/pipeline/", label: "パイプライン" },
  { href: "https://docs.fudoki.dev/", label: "API docs", external: true },
  { href: "/terms/", label: "利用条件" },
] as const

type LayoutProps = {
  children: ReactNode
  /**
   * ヘッダー右端に足す追加要素。パイプライン報告の「検査 passed/total」Badge のように
   * ページ固有の情報を Layout 自身は知らないので、slot として受ける。
   */
  headerExtra?: ReactNode
}

export function Layout({ children, headerExtra }: LayoutProps) {
  return (
    <ThemeProvider>
      <TooltipProvider>
        <div className="min-h-dvh bg-background text-foreground">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur">
            {/* ⚠️ ロゴを1枚にしない。`<img>` の中のメディアクエリは OS 設定しか見ないので、
                OS がライトのまま画面をダークにするとロゴだけ取り残される */}
            <a href="/" className="flex shrink-0 items-center gap-2" aria-label="fudoki ホーム">
              <img
                src={`${import.meta.env.BASE_URL}mark.svg`}
                alt="風土記"
                className="size-6 shrink-0 dark:hidden"
              />
              <img
                src={`${import.meta.env.BASE_URL}mark-dark.svg`}
                alt=""
                aria-hidden
                className="hidden size-6 shrink-0 dark:block"
              />
            </a>
            <nav className="flex items-center gap-4 text-sm">
              {NAV.map((n) => (
                <a
                  key={n.href}
                  href={n.href}
                  {...("external" in n ? { target: "_blank", rel: "noreferrer" } : {})}
                  className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                >
                  {n.label}
                </a>
              ))}
            </nav>
            <div className="ml-auto">{headerExtra}</div>
          </header>

          {children}

          <footer className="flex flex-wrap items-center gap-4 border-t px-4 py-6 text-xs text-muted-foreground">
            <a
              className="underline"
              href="https://github.com/wwwyo/fudoki"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
            <a className="underline" href="/terms/">
              ベータ利用条件
            </a>
          </footer>
        </div>
      </TooltipProvider>
    </ThemeProvider>
  )
}
