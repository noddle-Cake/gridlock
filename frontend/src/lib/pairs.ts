import type { CoordinationPair, PairProject } from '../types'

export type SortKey = 'score' | 'distance' | 'overlap' | 'start'

export const SORT_LABELS: Record<SortKey, string> = {
  score: 'Best opportunity',
  distance: 'Closest first',
  overlap: 'Most time overlap',
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
  /**
   * The server's matches for `query` (GET /search), which understands ZIP codes, states,
   * and company acronyms. Until it answers, the text is matched locally instead.
   */
  matchIds?: ReadonlySet<number> | null
}

function matches(p: PairProject, q: string): boolean {
  return [p.name, p.utility, p.location_ref, p.type, p.state].some((f) =>
    f?.toLowerCase().includes(q),
  )
}

/** Pairs whose utilities are both shown and where either project matches the search. */
export function filterPairs(pairs: CoordinationPair[], f: PairFilter): CoordinationPair[] {
  const q = f.query.trim().toLowerCase()
  const ids = q ? f.matchIds : null
  const hit = ids
    ? (p: PairProject) => ids.has(p.id)
    : (p: PairProject) => !q || matches(p, q)
  return pairs.filter(
    (pair) =>
      !f.hiddenUtilities.has(pair.project_a.utility) &&
      !f.hiddenUtilities.has(pair.project_b.utility) &&
      (hit(pair.project_a) || hit(pair.project_b)),
  )
}

/** Projects of the shown utilities that match the search (the Review table's scope). */
export function filterProjects<P extends PairProject>(projects: P[], f: PairFilter): P[] {
  const q = f.query.trim().toLowerCase()
  const ids = q ? f.matchIds : null
  return projects.filter(
    (p) => !f.hiddenUtilities.has(p.utility) && (ids ? ids.has(p.id) : !q || matches(p, q)),
  )
}

/** Above this many shown utilities the pair query asks for everything and filters locally. */
export const MAX_SCOPED_UTILITIES = 40

/**
 * Utilities to send with the pair query: the shown ones when only some are, so a two-utility
 * view fetches its few dozen pairs instead of every pair nationwide. Undefined = all pairs.
 */
export function pairScope(utilities: string[], hidden: ReadonlySet<string>): string[] | undefined {
  if (hidden.size === 0) return undefined
  const shown = utilities.filter((u) => !hidden.has(u))
  return shown.length <= MAX_SCOPED_UTILITIES ? shown : undefined
}

function placedIn(p: PairProject, b: ViewBounds): boolean {
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

/** Backend ranking: closest tier first, then composite score, then distance. */
export function compareRank(a: CoordinationPair, b: CoordinationPair): number {
  return (
    (a.tier ?? 99) - (b.tier ?? 99) ||
    b.scores.composite - a.scores.composite ||
    a.miles - b.miles
  )
}

export function sortPairs(pairs: CoordinationPair[], key: SortKey): CoordinationPair[] {
  const out = [...pairs]
  switch (key) {
    case 'distance':
      return out.sort((a, b) => a.miles - b.miles)
    case 'overlap':
      // Most shared build time first; then, among non-overlapping pairs, nearest in-service
      // dates. Undated pairs go last.
      return out.sort(
        (a, b) =>
          (b.overlap_ratio ?? -1) - (a.overlap_ratio ?? -1) ||
          (a.time_gap_days ?? Infinity) - (b.time_gap_days ?? Infinity),
      )
    case 'start':
      // Pairs without a shared window go last.
      return out.sort((a, b) =>
        (a.window_start ?? '\uffff').localeCompare(b.window_start ?? '\uffff'),
      )
    default:
      return out.sort(compareRank)
  }
}

/**
 * The two ends of a pair's map connector: the closest points of the two shapes (what the
 * distance measures) when the API sends them, else the two project markers.
 */
export function pairEnds(pair: CoordinationPair): [[number, number], [number, number]] {
  const { project_a: a, project_b: b, link } = pair
  if (link && link.length >= 2) return [link[0], link[link.length - 1]]
  return [
    [a.lat!, a.lng!],
    [b.lat!, b.lng!],
  ]
}

/** The best-ranked pair a project belongs to, if any. */
export function bestPairFor(p: PairProject, pairs: CoordinationPair[]): CoordinationPair | null {
  let best: CoordinationPair | null = null
  for (const pair of pairs) {
    if (pair.project_a.id !== p.id && pair.project_b.id !== p.id) continue
    if (!best || compareRank(pair, best) < 0) best = pair
  }
  return best
}

/** Score band used for the colored score chip on list cards. */
export function scoreBand(composite: number): 'high' | 'mid' | 'low' {
  return composite >= 0.7 ? 'high' : composite >= 0.45 ? 'mid' : 'low'
}
