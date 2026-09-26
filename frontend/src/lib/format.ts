import type { CostScope, DatePrecision } from '../types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.split('-').map(Number)
  return [y, m, d]
}

/** Label a materialized date at its source precision ("Q2 2026", "2027", ...). */
export function dateLabel(iso: string | null, precision: DatePrecision | null): string {
  if (!iso) return '—'
  const [y, m, d] = parts(iso)
  switch (precision) {
    case 'year':
      return String(y)
    case 'quarter':
      return `Q${Math.floor((m - 1) / 3) + 1} ${y}`
    case 'month':
      return `${MONTHS[m - 1]} ${y}`
    default:
      return `${MONTHS[m - 1]} ${d}, ${y}`
  }
}

export function dayLabel(iso: string): string {
  return dateLabel(iso, 'day')
}

/** "3 days", "5 months", "8.4 years" for a gap between schedules. */
export function gapLabel(days: number): string {
  if (days < 60) return `${days} ${days === 1 ? 'day' : 'days'}`
  if (days < 730) return `${Math.round(days / 30.4)} months`
  return `${(days / 365.25).toFixed(1)} years`
}

/** One-line timing summary: how much of the build time is shared, or how far apart it is. */
export function timingLabel(p: {
  overlap_ratio: number | null
  time_gap_days: number | null
}): string {
  if (p.overlap_ratio == null || p.time_gap_days == null) return 'schedule unknown'
  if (p.overlap_ratio > 0) return `${overlapPct(p.overlap_ratio)} build-time overlap`
  return `in service ${gapLabel(p.time_gap_days)} apart`
}

/** Like pct(), but never rounds a real overlap down to "0%". */
export function overlapPct(ratio: number): string {
  return ratio > 0 && ratio < 0.005 ? '<1%' : pct(ratio)
}

export function rangeLabel(
  start: string | null,
  end: string | null,
  sp: DatePrecision | null,
  ep: DatePrecision | null,
): string {
  if (!start || !end) return dateLabel(start ?? end, start ? sp : ep)
  const a = dateLabel(start, sp)
  const b = dateLabel(end, ep)
  return a === b ? a : `${a} – ${b}`
}

export function pct(x: number): string {
  return `${Math.round(x * 100)}%`
}

export const FACTOR_LABELS: Record<string, string> = {
  distance: 'Distance',
  overlap: 'Time overlap',
  type_similarity: 'Same project type',
  voltage_similarity: 'Voltage similarity',
}

// Fixed categorical order, validated for colour-vision deficiency. Never cycled: with hundreds
// of developers in the EIA data a repeating palette gave ~100 companies each colour, so only
// the busiest companies get a hue and everyone else shares OTHER_COLOR.
export const PALETTE = [
  '#2a78d6',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#4a3aa7',
  '#e34948',
]
export const OTHER_COLOR = '#8a8f96'

/** The `n` most frequent names (one entry per project), ties alphabetical. */
export function topUtilities(names: string[], n = PALETTE.length): string[] {
  const counts = new Map<string, number>()
  for (const u of names) counts.set(u, (counts.get(u) ?? 0) + 1)
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, n)
    .map(([u]) => u)
}

/**
 * Colours for the busiest utilities (pass one name per project). Assigned in alphabetical
 * order so they don't shuffle as counts shift; look up with `?? OTHER_COLOR`.
 */
export function utilityColors(names: string[]): Record<string, string> {
  const top = topUtilities(names).sort((a, b) => a.localeCompare(b))
  return Object.fromEntries(top.map((u, i) => [u, PALETTE[i]]))
}

export const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** $M -> "$850K", "$12.3M", "$240M", "$1.25B". */
export function money(musd: number | null | undefined): string {
  if (musd == null || !Number.isFinite(musd)) return '—'
  const sign = musd < 0 ? '−' : ''
  const x = Math.abs(musd)
  if (x >= 1000) return `${sign}$${(x / 1000).toFixed(2)}B`
  if (x >= 100) return `${sign}$${Math.round(x)}M`
  if (x >= 1) return `${sign}$${x.toFixed(1)}M`
  return `${sign}$${Math.round(x * 1000)}K`
}

export const SCOPE_LABELS: Record<CostScope, string> = {
  new_line: 'New line',
  line_rebuild: 'Line rebuild',
  reconductor: 'Reconductor',
  uprate: 'Line uprate (clearances)',
  line_terminal: 'Line terminal equipment',
  new_substation: 'New substation',
  substation_rebuild: 'Substation rebuild',
  expansion: 'Substation expansion / new terminal',
  transformer: 'Transformer',
  reactive: 'Capacitor / reactor / STATCOM',
  breaker: 'Breaker',
  protection: 'Protection / relay',
  retirement: 'Retirement',
  substation_general: 'Substation upgrade (scope unclear)',
}
