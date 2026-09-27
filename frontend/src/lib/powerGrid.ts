import type { VectorTile, VectorTileFeature } from '@mapbox/vector-tile'

// Base map is power-grid infrastructure only: OpenStreetMap power features served as vector
// tiles by Open Infrastructure Map (power lines, substations, plants, generators).

export const POWER_TILES_URL = 'https://openinframap.org/map/power/{z}/{x}/{y}.pbf'
export const POWER_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
  '<a href="https://openinframap.org/copyright">OpenInfraMap</a>'
/**
 * The map's own zoom floor, so the grid never switches off. Below zoom 5 OpenInfraMap already
 * thins its tiles to the 132 kV+ backbone (~300 KB each), so national views stay light.
 */
export const POWER_MIN_ZOOM = 3
export const POWER_MAX_NATIVE_ZOOM = 17

/** Line colour by voltage band (kV lower bound), matching Open Infrastructure Map's scale. */
export const VOLTAGE_SCALE: readonly [number, string][] = [
  [550, '#00C1CF'],
  [310, '#B54EB2'],
  [220, '#C73030'],
  [132, '#B55D00'],
  [52, '#B59F10'],
  [25, '#55B555'],
  [10, '#6E97B8'],
]
export const LOW_VOLTAGE_COLOR = '#7A7A85'
export const PLANT_COLOR = '#3F3F4A'

export function voltageColor(kv: number | null): string {
  if (kv == null) return LOW_VOLTAGE_COLOR
  return VOLTAGE_SCALE.find(([min]) => kv >= min)?.[1] ?? LOW_VOLTAGE_COLOR
}

/** Highest voltage a feature carries (multi-circuit lines list extras as voltage_2/_3), in kV. */
export function featureVoltage(props: Record<string, unknown>): number | null {
  const kvs = [props.voltage, props.voltage_2, props.voltage_3].filter(
    (v): v is number => typeof v === 'number' && Number.isFinite(v),
  )
  return kvs.length ? Math.max(...kvs) : null
}

/** Stroke width (CSS px): heavier for higher voltage, growing as the map zooms in. */
export function lineWidth(kv: number | null, zoom: number): number {
  const base = kv == null || kv < 25 ? 0.6 : kv < 132 ? 1 : kv < 310 ? 1.6 : 2.2
  return base * Math.min(2.5, Math.max(0.6, 0.6 + (zoom - 6) * 0.2))
}

type Ctx = Pick<
  CanvasRenderingContext2D,
  | 'beginPath'
  | 'moveTo'
  | 'lineTo'
  | 'closePath'
  | 'arc'
  | 'rect'
  | 'fill'
  | 'stroke'
  | 'setLineDash'
  | 'fillStyle'
  | 'strokeStyle'
  | 'lineWidth'
  | 'globalAlpha'
  | 'lineCap'
  | 'lineJoin'
>

type TileLike = Pick<VectorTile, 'layers'>

function features(tile: TileLike, name: string): VectorTileFeature[] {
  const layer = tile.layers[name]
  if (!layer) return []
  return Array.from({ length: layer.length }, (_, i) => layer.feature(i))
}

/**
 * Paint one vector tile onto a canvas context sized `size` CSS px square.
 * Draw order: plant footprints, then lines, then substation / plant / generator symbols.
 */
export function drawPowerTile(ctx: Ctx, tile: TileLike, zoom: number, size: number): void {
  const path = (f: VectorTileFeature, close: boolean) => {
    const k = size / f.extent
    ctx.beginPath()
    for (const ring of f.loadGeometry()) {
      ring.forEach((p, i) => (i ? ctx.lineTo(p.x * k, p.y * k) : ctx.moveTo(p.x * k, p.y * k)))
      if (close) ctx.closePath()
    }
  }
  const eachPoint = (f: VectorTileFeature, draw: (x: number, y: number) => void) => {
    const k = size / f.extent
    for (const ring of f.loadGeometry()) for (const p of ring) draw(p.x * k, p.y * k)
  }
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  for (const f of features(tile, 'power_plant')) {
    path(f, true)
    ctx.globalAlpha = 0.15
    ctx.fillStyle = PLANT_COLOR
    ctx.fill()
    ctx.globalAlpha = 0.6
    ctx.strokeStyle = PLANT_COLOR
    ctx.lineWidth = 1
    ctx.stroke()
  }

  // Low voltage first so the backbone draws on top.
  const lines = features(tile, 'power_line')
    .filter((f) => zoom >= 13 || (f.properties.line !== 'busbar' && f.properties.line !== 'bay'))
    .map((f) => ({ f, kv: featureVoltage(f.properties) }))
    .sort((a, b) => (a.kv ?? 0) - (b.kv ?? 0))
  for (const { f, kv } of lines) {
    const p = f.properties
    const hidden = p.location === 'underground' || p.tunnel === true
    path(f, false)
    ctx.globalAlpha = p.construction || p.disused ? 0.4 : 0.85
    ctx.strokeStyle = voltageColor(kv)
    ctx.lineWidth = lineWidth(kv, zoom)
    ctx.setLineDash(hidden || p.construction ? [4, 3] : [])
    ctx.stroke()
  }
  ctx.setLineDash([])

  if (zoom >= 13) {
    ctx.globalAlpha = 0.5
    ctx.fillStyle = '#E3B500'
    for (const f of features(tile, 'power_generator')) {
      eachPoint(f, (x, y) => {
        ctx.beginPath()
        ctx.arc(x, y, 1.5, 0, 2 * Math.PI)
        ctx.fill()
      })
    }
  }

  // Context, not the story: kept small so the opportunity markers drawn above stand out.
  const sub = zoom >= 10 ? 2.25 : 1.5
  for (const f of features(tile, 'power_substation_point')) {
    ctx.globalAlpha = 0.8
    ctx.fillStyle = voltageColor(featureVoltage(f.properties))
    ctx.strokeStyle = '#333'
    ctx.lineWidth = 0.5
    eachPoint(f, (x, y) => {
      ctx.beginPath()
      ctx.rect(x - sub, y - sub, sub * 2, sub * 2)
      ctx.fill()
      ctx.stroke()
    })
  }

  // Diamonds, so plants never read as the round project markers drawn above.
  const d = sub + 0.75
  for (const f of features(tile, 'power_plant_point')) {
    ctx.globalAlpha = 0.8
    ctx.fillStyle = PLANT_COLOR
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 0.5
    eachPoint(f, (x, y) => {
      ctx.beginPath()
      ctx.moveTo(x, y - d)
      ctx.lineTo(x + d, y)
      ctx.lineTo(x, y + d)
      ctx.lineTo(x - d, y)
      ctx.closePath()
      ctx.fill()
      ctx.stroke()
    })
  }
  ctx.globalAlpha = 1
}
