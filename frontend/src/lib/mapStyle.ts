import type { PathOptions } from 'leaflet'

import type { PairProject, Project, ProjectType } from '../types'
import { OTHER_COLOR, topUtilities } from './format'

export interface MarkerState {
  paired: boolean
  selected: boolean
}

/**
 * Marker styling: paired projects are highlighted, approximate ones hollow + dashed. Unpaired
 * projects stay small and faint: with ~2,000 on screen they are context, not the story.
 */
export function markerStyle(
  p: Project,
  color: string,
  s: MarkerState,
  scale = 1,
): PathOptions & { radius: number } {
  return {
    radius: s.selected ? 11 : Math.max(2, (s.paired ? 7 : 4) * scale),
    color: s.selected ? '#111' : color,
    weight: s.selected ? 3 : s.paired ? (scale < 1 ? 1.25 : 2) : 0.75,
    opacity: s.paired || s.selected ? 1 : 0.6,
    fillColor: color,
    fillOpacity: p.approximate ? 0.08 : s.paired || s.selected ? 0.85 : 0.3,
    dashArray: p.approximate ? '4 3' : undefined,
  }
}

/**
 * Marker size by zoom, in coarse steps so markers only restyle when a step changes: at
 * national scale full-size dots merge into blobs.
 */
export function markerScale(zoom: number): number {
  return zoom < 5 ? 0.5 : zoom < 7 ? 0.75 : 1
}

/** Below this zoom pair connectors (all under ~40 km) are specks; only the active pair draws. */
export const PAIR_LINE_MIN_ZOOM = 6

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
    const named = topUtilities(projects.map((p) => p.utility)).filter((u) => utilityColors[u])
    rows = named.map((u) => ({
      label: u,
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
