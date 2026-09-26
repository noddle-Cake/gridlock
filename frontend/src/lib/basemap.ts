// Reference base map (outlines, highways, place names) drawn from the static files that
// scripts/build-basemap.mjs writes to public/basemap/. Pure helpers live here; the Leaflet
// wiring is in components/BaseMap.tsx.

import type { MultiLineString } from 'geojson'
import { mesh } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'

export const BASEMAP_URL = `${import.meta.env.BASE_URL}basemap/`
export const BASEMAP_ATTRIBUTION = 'Boundaries &amp; roads: US Census Bureau, Natural Earth'

/** Zoom at which each lazily loaded layer starts to show. */
export const COUNTY_MIN_ZOOM = 8
export const HIGHWAY_MIN_ZOOM = 6
/** State names help when zoomed out; past this they crowd out town names. */
export const STATE_LABEL_MAX_ZOOM = 8.5
export const COUNTY_LABEL_MIN_ZOOM = 9.5
/** Cities this big are labelled ahead of state names. */
export const MAJOR_CITY = 250_000

/** [name, lat, lng] */
export type NamedPoint = [string, number, number]
/** [name, lat, lng, population]; population 0 = unincorporated place with no estimate. */
export type Place = [string, number, number, number]

export interface LabelData {
  states: NamedPoint[]
  places: Place[]
}

/** Smallest town population that earns a label at `zoom`; bigger places always win space first. */
export function minPlacePopulation(zoom: number): number {
  if (zoom < 5) return 1_000_000
  if (zoom < 6) return 300_000
  if (zoom < 7) return 100_000
  if (zoom < 8) return 40_000
  if (zoom < 9) return 15_000
  if (zoom < 10) return 5_000
  if (zoom < 11) return 1_000
  return 0
}

/** Font size class for a town label: cities read bigger than villages. */
export function placeTier(population: number): 'city' | 'town' | 'village' {
  return population >= 100_000 ? 'city' : population >= 10_000 ? 'town' : 'village'
}

export interface LabelCandidate {
  key: string
  /** Anchor in screen pixels. */
  x: number
  y: number
  /** Box the label occupies, relative to the anchor. */
  box: { left: number; top: number; width: number; height: number }
  /** Same-text labels (highway signs) closer than this many px are dropped as repeats. */
  repeatGap?: number
  text: string
}

/**
 * Greedy label placement: candidates are taken in order (most important first) and kept only
 * if their box doesn't overlap one already kept, with `padding` px of breathing room.
 */
export function layoutLabels(candidates: LabelCandidate[], padding = 3, limit = 400): Set<string> {
  const kept: { l: number; t: number; r: number; b: number }[] = []
  const lastByText = new Map<string, { x: number; y: number }[]>()
  const out = new Set<string>()
  for (const c of candidates) {
    if (out.size >= limit) break
    const l = c.x + c.box.left - padding
    const t = c.y + c.box.top - padding
    const r = l + c.box.width + 2 * padding
    const b = t + c.box.height + 2 * padding
    if (kept.some((k) => l < k.r && r > k.l && t < k.b && b > k.t)) continue
    if (c.repeatGap) {
      const same = lastByText.get(c.text) ?? []
      if (same.some((p) => Math.hypot(p.x - c.x, p.y - c.y) < c.repeatGap!)) continue
      lastByText.set(c.text, [...same, { x: c.x, y: c.y }])
    }
    kept.push({ l, t, r, b })
    out.add(c.key)
  }
  return out
}

/** Rough rendered width of `text` at `fontPx`, good enough for collision boxes. */
export function textWidth(text: string, fontPx: number): number {
  return Math.ceil(text.length * fontPx * 0.58)
}

/**
 * Points along a route to hang a highway sign on: one every `spacing` degrees of travel
 * along each line, so long routes get several signs and the layout thins the repeats.
 */
export function signPoints(lines: [number, number][][], spacing: number): [number, number][] {
  const out: [number, number][] = []
  for (const line of lines) {
    let travelled = spacing / 2
    for (let i = 1; i < line.length; i++) {
      const [x0, y0] = line[i - 1]
      const [x1, y1] = line[i]
      const seg = Math.hypot(x1 - x0, y1 - y0)
      while (travelled <= seg) {
        const t = travelled / seg
        out.push([y0 + (y1 - y0) * t, x0 + (x1 - x0) * t])
        travelled += spacing
      }
      travelled -= seg
    }
  }
  return out
}

/** Counties carry their state FIPS code as `st`; other objects carry no properties we use. */
type Collection = GeometryCollection<{ st?: string }>
type Shape = { properties?: { st?: string } }

/** Border lines between two different states. */
export function stateBorders(land: Topology): MultiLineString {
  return mesh(land, land.objects.states as Collection, (a, b) => a !== b)
}

/** Outer edge of the US and of each neighbouring country: coastlines and national borders. */
export function nationalOutlines(land: Topology): MultiLineString[] {
  return [
    mesh(land, land.objects.states as Collection, (a, b) => a === b),
    mesh(land, land.objects.countries as Collection),
  ]
}

/** Lines between counties of the same state (state lines are drawn separately, heavier). */
export function countyLines(counties: Topology): MultiLineString {
  return mesh(
    counties,
    counties.objects.counties as Collection,
    (a, b) => a !== b && (a as Shape).properties?.st === (b as Shape).properties?.st,
  )
}
