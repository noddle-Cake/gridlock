// Layout for the pair panel's build-window strip: both projects' windows on one time axis.

export type Span = [string, string] // ISO dates, inclusive

export interface WindowScale {
  /** Left edge and width of a span, in % of the axis. */
  place: (span: Span) => { left: number; width: number }
  /** January 1st of each year on the axis, with its position in %. */
  years: { year: number; at: number }[]
}

const DAY_MS = 86_400_000

function ms(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`)
}

/**
 * One axis covering every span, padded by a month each side so a bar never touches the edge.
 * Null when there is nothing to place.
 */
export function windowScale(spans: (Span | null | undefined)[]): WindowScale | null {
  const placed = spans.filter((s): s is Span => !!s)
  if (placed.length === 0) return null
  const lo = Math.min(...placed.map((s) => ms(s[0]))) - 30 * DAY_MS
  const hi = Math.max(...placed.map((s) => ms(s[1]) + DAY_MS)) + 30 * DAY_MS
  const pct = (t: number) => ((t - lo) / (hi - lo)) * 100
  const first = new Date(lo).getUTCFullYear() + 1
  const last = new Date(hi).getUTCFullYear()
  const years = []
  for (let y = first; y <= last; y++) years.push({ year: y, at: pct(Date.UTC(y, 0, 1)) })
  // Long axes (a decade between plans) label every other year so labels don't collide.
  const step = years.length > 8 ? 2 : 1
  return {
    place: ([start, end]) => {
      const left = pct(ms(start))
      return { left, width: Math.max(0.8, pct(ms(end) + DAY_MS) - left) }
    },
    years: years.filter((_, i) => i % step === 0),
  }
}
