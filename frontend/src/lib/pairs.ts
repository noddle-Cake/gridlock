import type { CoordinationPair, Project } from '../types'

export type SortKey = 'score' | 'distance' | 'overlap' | 'start'

export const SORT_LABELS: Record<SortKey, string> = {
  score: 'Highest score',
  distance: 'Closest first',
  overlap: 'Longest overlap',
  start: 'Soonest window',
}

/** Plain-object map extent (south/west/north/east), so it compares and tests without Leaflet. */
export interface ViewBounds {
  south: number
  west: number
  north: number
  east: number
}

export interface PairFilter {
  query: string
  hiddenUtilities: ReadonlySet<string>
}

function matches(p: Project, q: string): boolean {
  return [p.name, p.utility, p.location_ref, p.type, p.state].some((f) =>
    f?.toLowerCase().includes(q),
  )
}

/** Pairs whose utilities are both shown and where either project matches the search text. */
export function filterPairs(pairs: CoordinationPair[], f: PairFilter): CoordinationPair[] {
  const q = f.query.trim().toLowerCase()
  return pairs.filter(
    (pair) =>
      !f.hiddenUtilities.has(pair.project_a.utility) &&
      !f.hiddenUtilities.has(pair.project_b.utility) &&
      (!q || matches(pair.project_a, q) || matches(pair.project_b, q)),
  )
}

function placedIn(p: Project, b: ViewBounds): boolean {
  return (
    p.lat != null &&
    p.lng != null &&
    p.lat >= b.south &&
    p.lat <= b.north &&
    p.lng >= b.west &&
    p.lng <= b.east
  )
}

/** Pairs with at least one project inside the map view. Pairs with no location stay listed. */
export function pairsInView(pairs: CoordinationPair[], b: ViewBounds | null): CoordinationPair[] {
  if (!b) return pairs
  return pairs.filter((pair) => {
    const { project_a: a, project_b: c } = pair
    if (a.lat == null && c.lat == null) return true
    return placedIn(a, b) || placedIn(c, b)
  })
}

export function sortPairs(pairs: CoordinationPair[], key: SortKey): CoordinationPair[] {
  const out = [...pairs]
  switch (key) {
    case 'distance':
      return out.sort((a, b) => a.miles - b.miles)
    case 'overlap':
      return out.sort((a, b) => b.overlap_days - a.overlap_days)
    case 'start':
      return out.sort((a, b) => a.window_start.localeCompare(b.window_start))
    default:
      return out.sort((a, b) => b.scores.composite - a.scores.composite)
  }
}

/** The highest-scoring pair a project belongs to, if any. */
export function bestPairFor(p: Project, pairs: CoordinationPair[]): CoordinationPair | null {
  let best: CoordinationPair | null = null
  for (const pair of pairs) {
    if (pair.project_a.id !== p.id && pair.project_b.id !== p.id) continue
    if (!best || pair.scores.composite > best.scores.composite) best = pair
  }
  return best
}

/** Score band used for the colored score chip on list cards. */
export function scoreBand(composite: number): 'high' | 'mid' | 'low' {
  return composite >= 0.7 ? 'high' : composite >= 0.45 ? 'mid' : 'low'
}
