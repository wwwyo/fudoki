/**
 * 3ページ（/ ・ /pipeline/ ・ /terms/、将来 /analysis/）に共通する外枠。
 *
 * Vite の MPA なので、ページ間の遷移は素の `<a>` によるフルロードになる
 * （React Router は入れない）。ThemeProvider / TooltipProvider もここで1回だけ張る。
 */
import type { ReactNode } from "react"
import { ThemeProvider } from "@/components/theme-provider"
import { TooltipProvider } from "@/components/ui/tooltip"
import { withBase } from "@/lib/utils"

/**
 * `external` は別サイト（docs.fudoki.dev）への導線。新しいタブで開く。
 * ⚠️ ホームへの導線はロゴが持つので、ナビには置かない（同じ行き先が2つ並ぶ）。
 */
const NAV = [
  { href: "/pipeline/", label: "パイプライン" },
  { href: "https://docs.fudoki.dev/", label: "API docs", external: true },
  { href: "/terms/", label: "利用条件" },
] as const

type LayoutProps = {
  children: ReactNode
}

export function Layout({ children }: LayoutProps) {
  return (
    <ThemeProvider>
      <TooltipProvider>
        <div className="min-h-dvh bg-background text-foreground">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur">
            {/* ⚠️ ロゴを1枚にしない。`<img>` の中のメディアクエリは OS 設定しか見ないので、
                OS がライトのまま画面をダークにするとロゴだけ取り残される */}
            <a href={withBase("/")} className="flex shrink-0 items-center gap-2" aria-label="fudoki ホーム">
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
                  href={"external" in n ? n.href : withBase(n.href)}
                  {...("external" in n ? { target: "_blank", rel: "noreferrer" } : {})}
                  className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                >
                  {n.label}
                </a>
              ))}
            </nav>

            {/* ⚠️ lucide はブランドアイコンを持たない（配布をやめた）ので、
                GitHub のマークだけインラインの SVG で置く。依存は増やさない */}
            <a
              href="https://github.com/wwwyo/fudoki"
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub リポジトリ"
              className="text-muted-foreground hover:text-foreground ml-auto shrink-0 transition-colors"
            >
              <svg viewBox="0 0 16 16" aria-hidden className="size-5 fill-current">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
              </svg>
            </a>
          </header>

          {children}
        </div>
      </TooltipProvider>
    </ThemeProvider>
  )
}
