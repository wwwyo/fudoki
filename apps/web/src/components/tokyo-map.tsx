/**
 * 東京都62団体の地図。自治体をクリックするとその団体のパイプラインへ飛ぶ。
 *
 * ## なぜ素の SVG で描くか
 *
 * `apps/web` には地図系の依存が無く、増やさない方針（AGENTS.md）。東京都の範囲
 * （経度で約1度、緯度で約4度）は正距円筒図法に「基準緯度での横方向の補正
 * （`x = 経度 * cos(基準緯度)`）」を足すだけで、球面上の歪みが目に見える差になるほど
 * 広くない。本格的な投影法（Mercator 等）を実装・依存追加する理由が無い。
 *
 * ## なぜ島嶼部を別枠にするか
 *
 * 小笠原村は南鳥島（東経154度）・沖ノ鳥島（北緯20度）まで行政区域に含む。
 * 本土と同じ座標系に置くと、23区どころか伊豆諸島まで潰れて豆粒になる
 * （東京都自身の地図も別枠方式を採っている）。
 */
import { useEffect, useMemo, useState } from 'react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn, withBase } from '@/lib/utils'

type TokyoFeature = {
  type: 'Feature'
  properties: { code: string; name: string; island: boolean }
  geometry: { type: 'MultiPolygon'; coordinates: number[][][][] }
}

type TokyoGeoJSON = { type: 'FeatureCollection'; features: TokyoFeature[] }

type Props = {
  className?: string
}

/** 島の1ポリゴン。`MultiPolygon.coordinates` の要素（=リングの配列。先頭が外周） */
type Polygon = number[][][]

/** 経度緯度 → 平面座標。基準緯度1つで足りる範囲（東京都）でしか正しくない、局所投影 */
type Project = (lon: number, lat: number) => [number, number]

function makeProjector(lonMin: number, latMax: number, refLat: number, scale: number): Project {
  const cosRef = Math.cos((refLat * Math.PI) / 180)
  // y は南北を反転する（緯度は北ほど大きいが、SVG の y は下ほど大きい）
  return (lon, lat) => [(lon - lonMin) * cosRef * scale, (latMax - lat) * scale]
}

/** シューレースの公式。外周の面積（島のクラスタリングで「本体」を選ぶための重み） */
function ringArea(ring: number[][]): number {
  let a = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i]
    const [x2, y2] = ring[i + 1]
    a += x1 * y2 - x2 * y1
  }
  return Math.abs(a) / 2
}

function bboxOf(ring: number[][]) {
  const xs = ring.map((c) => c[0])
  const ys = ring.map((c) => c[1])
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
}

/**
 * 面積最大のポリゴンから一定距離内にあるものだけを残す。
 *
 * ⚠️ **小笠原村の座標をそのまま使うと表示が壊れる。** 村の行政区域には南鳥島・沖ノ鳥島という
 * 本島から1,000km前後離れた岩礁が含まれ、外接矩形で正規化すると本島群が点になる。
 * 「どこまでを表示するか」を村ごとに手で決めると判断が団体固有になるので、
 * 距離で機械的に切る（本島群どうしは数度以内に収まり、離島の岩礁だけが外れる）。
 * 他の8町村は元々1クラスタなので、この処理は実質何もしない。
 */
function mainCluster(polygons: Polygon[], maxDistanceDeg = 4): Polygon[] {
  if (polygons.length <= 1) return polygons
  const withMeta = polygons.map((poly) => {
    const outer = poly[0]
    const { minX, maxX, minY, maxY } = bboxOf(outer)
    return { poly, area: ringArea(outer), cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 }
  })
  const anchor = withMeta.reduce((a, b) => (b.area > a.area ? b : a))
  const kept = withMeta.filter((p) => Math.hypot(p.cx - anchor.cx, p.cy - anchor.cy) <= maxDistanceDeg)
  return kept.map((p) => p.poly)
}

/** MultiPolygon を1つの `<path d>` に。穴は evenodd で処理する（外周と穴の巻き方向を仮定しない） */
function pathFromPolygons(polygons: Polygon[], project: Project): string {
  return polygons
    .map((poly) =>
      poly
        .map((ring) => {
          const pts = ring.map(([lon, lat]) => project(lon, lat).join(','))
          return `M${pts.join('L')}Z`
        })
        .join(' '),
    )
    .join(' ')
}

function outerBboxOf(polygons: Polygon[]) {
  const rings = polygons.map((p) => p[0])
  const minX = Math.min(...rings.map((r) => bboxOf(r).minX))
  const maxX = Math.max(...rings.map((r) => bboxOf(r).maxX))
  const minY = Math.min(...rings.map((r) => bboxOf(r).minY))
  const maxY = Math.max(...rings.map((r) => bboxOf(r).maxY))
  return { minX, maxX, minY, maxY }
}

const MAINLAND_WIDTH = 640
/** 島タイル。実面積は極端に小さいので実寸比では並べず、正方形に収めて「押せる大きさ」を優先する */
const ISLAND_TILE = 84
const ISLAND_TILE_PAD = 14

function useTokyoGeoJSON() {
  const [state, setState] = useState<{ data: TokyoGeoJSON | null; error: string | null }>({
    data: null,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    // tokyo.geojson は pipeline の生成物ではなく commit 済みの静的アセット（apps/web/map/build.py）。
    // report / detail の JSON と違って実行のたびには変わらないので、
    // lib/pipeline.ts の `cache: 'no-store'` は真似しない（無意味にキャッシュを捨てるだけになる）
    fetch(`${import.meta.env.BASE_URL}tokyo.geojson`)
      .then((res) => {
        if (!res.ok) throw new Error(`tokyo.geojson を読めません（HTTP ${res.status}）`)
        return res.json() as Promise<TokyoGeoJSON>
      })
      .then((data) => {
        if (!cancelled) setState({ data, error: null })
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ data: null, error: err instanceof Error ? err.message : String(err) })
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}

export function TokyoMap({ className }: Props) {
  const { data, error } = useTokyoGeoJSON()

  const mainland = useMemo(() => {
    if (!data) return null
    const features = data.features.filter((f) => !f.properties.island)
    const bbox = outerBboxOf(features.flatMap((f) => f.geometry.coordinates))
    const refLat = (bbox.minY + bbox.maxY) / 2
    const cosRef = Math.cos((refLat * Math.PI) / 180)
    const lonSpan = (bbox.maxX - bbox.minX) * cosRef
    const latSpan = bbox.maxY - bbox.minY
    const scale = MAINLAND_WIDTH / lonSpan
    const project = makeProjector(bbox.minX, bbox.maxY, refLat, scale)
    return {
      width: MAINLAND_WIDTH,
      height: latSpan * scale,
      shapes: features.map((f) => ({
        code: f.properties.code,
        name: f.properties.name,
        d: pathFromPolygons(f.geometry.coordinates, project),
      })),
    }
  }, [data])

  const islands = useMemo(() => {
    if (!data) return []
    return data.features
      .filter((f) => f.properties.island)
      .map((f) => {
        const polygons = mainCluster(f.geometry.coordinates)
        const bbox = outerBboxOf(polygons)
        const refLat = (bbox.minY + bbox.maxY) / 2
        const cosRef = Math.cos((refLat * Math.PI) / 180)
        const lonSpan = (bbox.maxX - bbox.minX) * cosRef || 1
        const latSpan = bbox.maxY - bbox.minY || 1
        const inner = ISLAND_TILE - ISLAND_TILE_PAD * 2
        // 正方形タイルに contain で収める。島は細長いものが多く、
        // 縦横どちらかいっぱいに引き伸ばすと形が別物になる
        const scale = Math.min(inner / lonSpan, inner / latSpan)
        const drawnWidth = lonSpan * scale
        const drawnHeight = latSpan * scale
        const offsetX = ISLAND_TILE_PAD + (inner - drawnWidth) / 2
        const offsetY = ISLAND_TILE_PAD + (inner - drawnHeight) / 2
        const project: Project = (lon, lat) => {
          const [x, y] = makeProjector(bbox.minX, bbox.maxY, refLat, scale)(lon, lat)
          return [x + offsetX, y + offsetY]
        }
        return {
          code: f.properties.code,
          name: f.properties.name,
          d: pathFromPolygons(polygons, project),
        }
      })
  }, [data])

  if (error) {
    return <p className={cn('text-sm text-destructive', className)}>地図を読み込めませんでした（{error}）</p>
  }

  if (!data || !mainland) {
    return (
      <div className={cn('flex aspect-4/3 items-center justify-center text-sm text-muted-foreground', className)}>
        地図を読み込み中…
      </div>
    )
  }

  return (
    <figure className={cn('flex flex-col gap-3', className)}>
      <svg
        viewBox={`0 0 ${mainland.width} ${mainland.height}`}
        width={mainland.width}
        height={mainland.height}
        className="h-auto w-full max-w-2xl"
        role="img"
        aria-label="東京都の区市町村。クリックするとその団体のパイプラインへ移動します"
      >
        {mainland.shapes.map((s) => (
          <Tooltip key={s.code}>
            <TooltipTrigger
              render={<a href={withBase(`/pipeline/${s.code}/`)} aria-label={s.name} className="group outline-none" />}
            >
              <path
                d={s.d}
                className={cn(
                  'fill-muted stroke-background cursor-pointer stroke-[0.6] transition-opacity',
                  'group-hover:opacity-70 group-focus-visible:opacity-70',
                  'group-focus-visible:stroke-ring group-focus-visible:stroke-[1.5]',
                )}
              />
            </TooltipTrigger>
            <TooltipContent>{s.name}</TooltipContent>
          </Tooltip>
        ))}
      </svg>

      {/* ⚠️ 島しょ部だけ縮尺が本土と揃っていない。小笠原村は南鳥島・沖ノ鳥島まで
          行政区域に含み、本土と同じ座標系では点にしかならないため、タイルごとに
          正規化して並べている（各タイルの中でだけ形が正しい）。 */}
      <div className="flex flex-wrap gap-2">
        {islands.map((s) => (
          <Tooltip key={s.code}>
            <TooltipTrigger
              render={
                <a
                  href={withBase(`/pipeline/${s.code}/`)}
                  aria-label={s.name}
                  className="group focus-visible:ring-ring/50 flex flex-col items-center gap-0.5 rounded-md p-1 outline-none focus-visible:ring-[3px]"
                />
              }
            >
              <svg viewBox={`0 0 ${ISLAND_TILE} ${ISLAND_TILE}`} width={ISLAND_TILE} height={ISLAND_TILE} aria-hidden>
                {/* タイル全面を透明な矩形で覆い、実面積に関係なく同じ大きさを押せるようにする */}
                <rect width={ISLAND_TILE} height={ISLAND_TILE} className="fill-transparent" />
                <path
                  d={s.d}
                  className="fill-muted stroke-background stroke-[0.6] transition-opacity group-hover:opacity-70"
                />
              </svg>
              <span className="text-muted-foreground max-w-[84px] truncate text-[10px]">{s.name}</span>
            </TooltipTrigger>
            <TooltipContent>{s.name}</TooltipContent>
          </Tooltip>
        ))}
      </div>

      <figcaption className="text-[10px] leading-relaxed text-muted-foreground/70">
        出典: 国土交通省 国土数値情報（行政区域データ）。測量法に基づく国土地理院長承認（複製）R 5JHf 357
      </figcaption>
    </figure>
  )
}
