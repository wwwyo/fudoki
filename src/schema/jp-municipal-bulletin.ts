import { z } from 'zod'

/**
 * # jp-municipal-bulletin/1.0
 *
 * 日本の自治体が「議会だより」等の広報紙をオープンデータとして配布するときに
 * **事実上使われている CSV の共通形式**。
 *
 * ## これは何で、何ではないか
 *
 * - **実測にもとづく de facto standard。** 東京都62区市町村のうち議会だよりを
 *   公開している42団体の CSV を実際に取得したところ、**40団体でヘッダが完全に一致**した
 *   （2026-08-10 実測）。残り2団体も拡張列や引用符の差だけで、意味的には同じ。
 * - **公式の標準ではない。** デジタル庁の「自治体標準オープンデータセット」
 *   （旧・推奨データセット、政府相互運用性フレームワーク GIF の一部）の
 *   データ項目定義書A（2025-05-01）およびデータモデル型（2023-10-18 / 2023-03-31）を
 *   実際にダウンロードして全シートを確認したが、**広報紙のテーマは収録されていない**。
 * - したがって**この形式に公式な名前は存在せず、kotonoha が観測事実に名前を与えたもの**。
 *   一致の出所は未特定（東京都が区市町村へテンプレートを配っている可能性、
 *   ある自治体の形式が伝播した可能性などがあるが確認していない）。
 *
 * ## 特徴
 *
 * - 先頭列が **全国地方公共団体コード**。kotonoha の主キーとそのまま一致する
 * - `町字ID` はデジタル庁のアドレス・ベース・レジストリの語彙
 * - 本文は持たず、**発行号のメタデータと PDF への URL** だけを持つ
 *
 * @see 実測の内訳は src/extract/sources/manifest.json の
 *      openData.gikaiDayori.schemaCheck を参照
 */
export const BULLETIN_SCHEMA_ID = 'jp-municipal-bulletin/1.0' as const

/** 正準の列名（この順序で現れる） */
export const BULLETIN_COLUMNS = [
  '全国地方公共団体コード',
  'ID',
  '地方公共団体名',
  '名称',
  '号数',
  '発行年月',
  '発行元',
  '町字ID',
  '発行元所在地_都道府県',
  '発行元所在地_市区町村',
  '発行元所在地_町字',
  '発行元所在地_番地以下',
  '発行元所在地_建物名等(方書)',
  '発行元連絡先（電話番号）',
  '発行元連絡先（メールアドレス）',
  'URL',
] as const

/**
 * 実測で見つかった表記ゆれ。括弧の全角/半角とアンダースコア化が主。
 * 例: 中野区は `発行元所在地_建物名等_方書_` `発行元連絡先_電話番号_` を使う。
 */
const ALIASES: Record<string, (typeof BULLETIN_COLUMNS)[number]> = {
  発行元所在地_建物名等_方書_: '発行元所在地_建物名等(方書)',
  発行元連絡先_電話番号_: '発行元連絡先（電話番号）',
  発行元連絡先_メールアドレス_: '発行元連絡先（メールアドレス）',
  '発行元所在地_建物名等（方書）': '発行元所在地_建物名等(方書)',
  '発行元連絡先(電話番号)': '発行元連絡先（電話番号）',
  '発行元連絡先(メールアドレス)': '発行元連絡先（メールアドレス）',
}

/**
 * 内容に関係しない列。
 * - `_id` は CKAN の DataStore が付与する
 * - 空文字は行末カンマによる末尾の空列（荒川区・東久留米市で実測）
 */
const IGNORED = new Set(['_id', ''])

/** 列名を正準形へ寄せる。BOM と前後空白も落とす */
export function normalizeColumn(name: string): string {
  const t = name.replace(/^﻿/, '').trim()
  return ALIASES[t] ?? t
}

export const BulletinRow = z.object({
  /** 全国地方公共団体コード（6桁）。kotonoha の主キー */
  団体コード: z.string().regex(/^\d{6}$/),
  地方公共団体名: z.string(),
  /** 紙面の名称。「議会だより」「めぐろ区議会だより」など自治体ごとに揺れる */
  名称: z.string(),
  号数: z.string().nullable(),
  /** YYYY-MM 形式が多いが保証はない。生値のまま持つ */
  発行年月: z.string().nullable(),
  発行元: z.string().nullable(),
  /** 紙面 PDF の URL。本文はここから取る */
  url: z.url().nullable(),
})
export type BulletinRow = z.infer<typeof BulletinRow>

export type Conformance = 'conformant' | 'variant' | 'broken'

export type ConformanceResult = {
  conformance: Conformance
  /** 正準列のうち欠けているもの */
  missing: string[]
  /** 正準に無い追加列（GIS用住所・経度・緯度・分類 などの実例がある） */
  extra: string[]
  columns: number
}

/** ヘッダ行を jp-municipal-bulletin/1.0 と突き合わせる */
export function checkConformance(header: readonly string[]): ConformanceResult {
  const cols = header.map(normalizeColumn).filter((c) => !IGNORED.has(c))
  const set = new Set(cols)
  const missing = BULLETIN_COLUMNS.filter((c) => !set.has(c))
  const extra = cols.filter((c) => !(BULLETIN_COLUMNS as readonly string[]).includes(c))
  // 正準列が定義順に並んでいるか（追加列は末尾にあってもよい）
  const canonical = cols.filter((c) => (BULLETIN_COLUMNS as readonly string[]).includes(c))
  const inOrder = canonical.every((c, i) => c === BULLETIN_COLUMNS[i])
  const conformance: Conformance =
    missing.length > 0 ? 'broken' : extra.length === 0 && inOrder ? 'conformant' : 'variant'
  return { conformance, missing, extra, columns: cols.length }
}

/** 正準形に寄せた行へ写す。列が欠けている場合は null を入れる */
export function toRow(header: readonly string[], values: readonly string[]): BulletinRow {
  const cols = header.map(normalizeColumn)
  const at = (name: string) => {
    const i = cols.indexOf(name)
    const v = i >= 0 ? values[i]?.trim() : undefined
    return v ? v : null
  }
  return BulletinRow.parse({
    団体コード: at('全国地方公共団体コード') ?? '',
    地方公共団体名: at('地方公共団体名') ?? '',
    名称: at('名称') ?? '',
    号数: at('号数'),
    発行年月: at('発行年月'),
    発行元: at('発行元'),
    url: at('URL'),
  })
}
