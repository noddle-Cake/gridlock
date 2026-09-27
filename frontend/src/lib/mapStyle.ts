import type { PathOptions } from 'leaflet'

import type { PairProject, Project, ProjectType } from '../types'
import { OTHER_COLOR, topUtilities } from './format'

export interface MarkerState {
  paired: boolean
  selected: boolean
  /** Outline for paired dots in the map's land colour, keeping clustered ones apart. */
  halo?: string
}

/**
 * Marker styling at `zoom`: paired projects are highlighted, approximate ones hollow + dashed.
 * Unpaired projects stay small and faint: with ~2,000 on screen they are context, not the
 * story. Radius and weight follow the zoom; the map's canvas re-evaluates them every frame.
 */
export function markerStyle(
  p: Project,
  color: string,
  s: MarkerState,
  zoom = Infinity,
): PathOptions & { radius: number; weight: number } {
  const hl = highlightSize(zoom)
  const scale = markerScale(zoom)
  // Approximate dots are drawn by their dashed outline, so they keep their colour.
  const halo = s.paired && !p.approximate ? s.halo : undefined
  return {
    radius: s.selected ? hl.radius : Math.max(2, (s.paired ? 9 : 4) * scale),
    color: s.selected ? '#111' : (halo ?? color),
    weight: s.selected
      ? hl.weight
      : s.paired
        ? Math.max(1, (halo ? 1.5 : 2.5) * scale)
        : 0.75,
    opacity: s.paired || s.selected ? 1 : 0.6,
    fillColor: color,
    fillOpacity: p.approximate ? 0.08 : s.paired || s.selected ? 0.85 : 0.3,
    dashArray: p.approximate ? '4 3' : undefined,
  }
}

/**
 * Marker size by zoom, about a third at national scale (larger dots merge into blobs over the
 * hundreds of paired projects there) growing smoothly to full size by zoom 7.5.
 */
export function markerScale(zoom: number): number {
  return Math.min(1, Math.max(0.35, 0.35 + (zoom - 4) * 0.19))
}

/**
 * Size of an opened or hovered pair's markers: shrinks with the view so it never dwarfs its
 * neighbours when zoomed out, and stays larger than any other paired marker.
 */
export function highlightSize(zoom: number): { radius: number; weight: number } {
  const radius = Math.min(13, Math.max(7, 7 + (zoom - 4) * 1.75))
  return { radius, weight: (radius * 3) / 13 }
}

const PAIR_INK = { light: { idle: '#2b3440', active: '#111' }, dark: { idle: '#d5dce3', active: '#fff' } }
const PAIR_HALO = { light: '#ffffff', dark: '#10161c' }

/**
 * A pair connector's line and the halo drawn under it. Idle connectors are a chain of round
 * dots: county lines are dashed, state lines dash-dotted and the power grid solid, so dots
 * stay recognisable among them, and the halo lifts them off the grid lines they cross.
 * Opened or hovered pairs are solid and heavier. Zoomed out past the pair detail zoom
 * (`far`) connectors are only faint hints and the halo is hidden, not removed: a halo added
 * after its line would be drawn over it.
 */
export function pairLineStyle(
  { active, selected, far, scheme }: { active: boolean; selected: boolean; far: boolean; scheme: 'light' | 'dark' },
): { line: PathOptions; halo: PathOptions } {
  const color = selected ? PAIR_INK[scheme].active : PAIR_INK[scheme].idle
  if (far && !active) {
    return {
      line: { color, weight: 1, opacity: 0.15, dashArray: undefined },
      halo: { color: PAIR_HALO[scheme], weight: 0, opacity: 0, interactive: false },
    }
  }
  const weight = active ? 4.5 : 3
  return {
    line: {
      color,
      weight,
      opacity: active ? 0.95 : 0.85,
      lineCap: 'round',
      dashArray: active ? undefined : '0.1 6.5',
    },
    halo: { color: PAIR_HALO[scheme], weight: weight + 3.5, opacity: 0.85, lineCap: 'round', interactive: false },
  }
}

/** Ring colour for a touching pair's connector, matching `pairLineStyle`. */
export function pairInk(selected: boolean, scheme: 'light' | 'dark'): string {
  return selected ? PAIR_INK[scheme].active : PAIR_INK[scheme].idle
}

export type ColorBy ='type' | 'utility' | 'year'
export const COLOR_BY_OPTIONS: [ColorBy, string][] = [
  ['type', 'Type'],
  ['utility', 'Company'],
  ['year', 'Start year'],
]

// Types take the first three categorical slots: the only ones that stay distinguishable
// (incl. colour-blind) when every pair of colours can sit side by side, as on a map.
const TYPE_ORDER: [ProjectType, string][] = [
  ['generation', 'Generation'],
  ['transmission line', 'Transmission line'],
  ['substation', 'Substation'],
]
const TYPE_COLORS: Record<'light' | 'dark', Record<ProjectType, string>> = {
  light: { generation: '#2a78d6', 'transmission line': '#eb6834', substation: '#1baf7a' },
  dark: { generation: '#3987e5', 'transmission line': '#d95926', substation: '#199e70' },
}

// One-hue ordinal ramp, soonest most prominent (darkest on light, lightest on dark).
const YEAR_FIRST = 2026
const YEAR_BINS = 5 // 2026 … 2029, then 2030+
const YEAR_RAMP: Record<'light' | 'dark', string[]> = {
  light: ['#0d366b', '#1c5cab', '#2a78d6', '#5598e7', '#86b6ef'],
  dark: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf'],
}

function yearBin(p: PairProject): number | null {
  const iso = p.start_date ?? p.end_date
  if (!iso) return null
  const y = Number(iso.slice(0, 4))
  return Math.min(YEAR_BINS - 1, Math.max(0, y - YEAR_FIRST))
}

function yearLabel(bin: number): string {
  const y = YEAR_FIRST + bin
  return bin === 0 ? `${y} or earlier` : bin === YEAR_BINS - 1 ? `${y}+` : String(y)
}

/** Fill colour for a project under the chosen encoding. */
export function projectColor(
  p: PairProject,
  by: ColorBy,
  utilityColors: Record<string, string>,
  scheme: 'light' | 'dark' = 'light',
): string {
  if (by === 'utility') return utilityColors[p.utility] ?? OTHER_COLOR
  if (by === 'type') return (p.type && TYPE_COLORS[scheme][p.type]) || OTHER_COLOR
  const bin = yearBin(p)
  return bin == null ? OTHER_COLOR : YEAR_RAMP[scheme][bin]
}

export interface LegendEntry {
  label: string
  color: string
  count: number
}

/** Legend rows for the chosen encoding, with project counts; empty categories are dropped. */
export function colorLegend(
  projects: Project[],
  by: ColorBy,
  utilityColors: Record<string, string>,
  scheme: 'light' | 'dark' = 'light',
  /** The signed-in user's company: listed first and marked, whatever its project count. */
  own: string | null = null,
): LegendEntry[] {
  const count = (pred: (p: Project) => boolean) => projects.filter(pred).length
  let rows: LegendEntry[]
  let rest: LegendEntry
  if (by === 'type') {
    rows = TYPE_ORDER.map(([t, label]) => ({
      label,
      color: TYPE_COLORS[scheme][t],
      count: count((p) => p.type === t),
    }))
    rest = { label: 'Type unknown', color: OTHER_COLOR, count: count((p) => !p.type) }
  } else if (by === 'year') {
    rows = YEAR_RAMP[scheme].map((color, bin) => ({
      label: yearLabel(bin),
      color,
      count: count((p) => yearBin(p) === bin),
    }))
    rest = { label: 'Undated', color: OTHER_COLOR, count: count((p) => yearBin(p) == null) }
  } else {
    // Every coloured company on the map, busiest first; the user's own company leads.
    const named = topUtilities(projects.map((p) => p.utility), Infinity)
      .filter((u) => utilityColors[u])
      .sort((a, b) => Number(b === own) - Number(a === own))
    rows = named.map((u) => ({
      label: u === own ? `${u} (you)` : u,
      color: utilityColors[u],
      count: count((p) => p.utility === u),
    }))
    const others = new Set(projects.map((p) => p.utility).filter((u) => !utilityColors[u]))
    rest = {
      label: `Other (${others.size} ${others.size === 1 ? 'company' : 'companies'})`,
      color: OTHER_COLOR,
      count: count((p) => !utilityColors[p.utility]),
    }
  }
  return [...rows, rest].filter((r) => r.count > 0)
}
