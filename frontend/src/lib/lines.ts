import type { LatLngBoundsExpression, PathOptions } from 'leaflet'

import type { LineCollection, LineFeature } from '../types'

export const UNKNOWN_OWNER = 'Owner not published'
const UNKNOWN_COLOR = '#868e96'

/** Thin for sub-transmission, heavier for the 230 kV+ backbone. */
export function lineWeight(kv: number | null): number {
  if (kv == null) return 1
  if (kv >= 300) return 3
  if (kv >= 200) return 2.2
  if (kv >= 100) return 1.5
  return 1
}

export function lineStyle(f: LineFeature, colors: Record<string, string>): PathOptions {
  const owner = f.properties.owner_norm
  return {
    color: owner ? (colors[owner] ?? UNKNOWN_COLOR) : UNKNOWN_COLOR,
    weight: lineWeight(f.properties.voltage_kv),
    opacity: 0.6,
    dashArray: owner ? undefined : '2 4',
  }
}

/** Owners by line count, most first; lines without an owner last. */
export function lineOwners(lines: LineCollection): { owner: string | null; count: number }[] {
  const counts = new Map<string | null, number>()
  for (const f of lines.features) {
    const o = f.properties.owner_norm
    counts.set(o, (counts.get(o) ?? 0) + 1)
  }
  return [...counts]
    .map(([owner, count]) => ({ owner, count }))
    .sort((a, b) =>
      a.owner == null ? 1 : b.owner == null ? -1 : b.count - a.count || a.owner.localeCompare(b.owner),
    )
}

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** Tooltip HTML (Leaflet's bindTooltip takes a string), with every field escaped. */
export function lineTooltip(f: LineFeature): string {
  const p = f.properties
  const ends = [p.sub_1, p.sub_2].filter((s): s is string => !!s && !/^(TAP|UNKNOWN)\d/.test(s))
  const parts = [
    `<strong>${esc(p.owner_norm ?? UNKNOWN_OWNER)}</strong>`,
    esc(p.voltage_kv ? `${p.voltage_kv} kV existing line` : 'Existing line, voltage unknown'),
  ]
  if (ends.length) parts.push(esc(ends.join(' – ')))
  if (p.owner && p.owner_norm && p.owner.toUpperCase() !== p.owner_norm.toUpperCase()) {
    parts.push(`<em>HIFLD owner: ${esc(p.owner)}</em>`)
  }
  return parts.join('<br/>')
}

export function lineBounds(lines: LineCollection): LatLngBoundsExpression | null {
  let minLat = Infinity
  let minLng = Infinity
  let maxLat = -Infinity
  let maxLng = -Infinity
  for (const f of lines.features) {
    for (const part of f.geometry.coordinates) {
      for (const [lng, lat] of part) {
        if (lat < minLat) minLat = lat
        if (lat > maxLat) maxLat = lat
        if (lng < minLng) minLng = lng
        if (lng > maxLng) maxLng = lng
      }
    }
  }
  return Number.isFinite(minLat)
    ? [
        [minLat, minLng],
        [maxLat, maxLng],
      ]
    : null
}
