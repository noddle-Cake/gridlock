import type { LatLngBoundsExpression, PathOptions } from 'leaflet'

import type { LineCollection, LineFeature } from '../types'
import { escapeHtml as esc } from './format'
import { voltageColor } from './powerGrid'

export const UNKNOWN_OWNER = 'Owner not published'

/** Thin for sub-transmission, heavier for the 230 kV+ backbone. */
export function lineWeight(kv: number | null): number {
  if (kv == null) return 1
  if (kv >= 300) return 3
  if (kv >= 200) return 2.2
  if (kv >= 100) return 1.5
  return 1
}

/**
 * Coloured by voltage on the power-grid layer's scale, so an existing line reads the same
 * on both layers and project colours stay free for projects. The owner is in the tooltip.
 */
export function lineStyle(f: LineFeature): PathOptions {
  const kv = f.properties.voltage_kv
  return {
    color: voltageColor(kv),
    weight: lineWeight(kv),
    opacity: 0.7,
    dashArray: f.properties.owner_norm ? undefined : '2 4',
  }
}

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
