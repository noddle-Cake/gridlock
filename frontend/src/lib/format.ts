import type { DatePrecision } from '../types'

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

/** One-line timing summary for a pair: shared window, or how far apart the schedules are. */
export function timingLabel(p: {
  overlap_days: number
  time_gap_days: number | null
}): string {
  if (p.time_gap_days == null) return 'schedule unknown'
  if (p.overlap_days > 0) return `${p.overlap_days} d build-window overlap`
  return `in service ${gapLabel(p.time_gap_days)} apart`
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

/** "$340k", "$1.2M". */
export function usd(x: number): string {
  if (x >= 1_000_000) return `$${(x / 1_000_000).toFixed(x >= 10_000_000 ? 0 : 1)}M`
  if (x >= 1_000) return `$${Math.round(x / 1_000)}k`
  return `$${Math.round(x)}`
}

/** "$340k–$1.0M". */
export function usdRange(low: number, high: number): string {
  return low === high ? usd(low) : `${usd(low)}–${usd(high)}`
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

// Distinct hues (no two oranges): project utilities and HIFLD line owners share this map.
const PALETTE = [
  '#2f6fdf',
  '#d9480f',
  '#2b8a3e',
  '#9c36b5',
  '#c2255c',
  '#0b7285',
  '#8c5a2b',
  '#5c940d',
  '#b8860b',
  '#e64980',
]

/** Stable categorical color per utility (sorted order, so colors don't shuffle). */
export function utilityColors(utilities: string[]): Record<string, string> {
  const sorted = [...new Set(utilities)].sort((a, b) => a.localeCompare(b))
  return Object.fromEntries(sorted.map((u, i) => [u, PALETTE[i % PALETTE.length]]))
}
