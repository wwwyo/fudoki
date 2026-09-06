import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * サイト内リンクの href。
 *
 * ⚠️ **`href="/pipeline/"` のように絶対パスで直接書かない。** いまはルート配信なので
 * どちらでも動くが、置き場をサブパスへ移したとき、絶対パスのリンクだけが
 * ドメインルートへ飛んで壊れる（`vite.config.ts` の `base` は静的アセットの
 * URL しか直さない）。`BASE_URL` はビルド時に確定するので実行時のコストは無い。
 */
export function withBase(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\//, "")}`
}
