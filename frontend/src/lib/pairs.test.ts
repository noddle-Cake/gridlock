import { describe, expect, it } from 'vitest'

import { pair, project } from '../test/fixtures'
import {
  bestPairFor,
  filterPairs,
  filterProjects,
  pairEnds,
  pairScope,
  pairsInView,
  sortPairs,
} from './pairs'

const near = pair()
const far = pair({
  id: '3-4',
  project_a: project({ id: 3, name: 'Tampa bank', utility: 'Gulf Power', lat: 27.9, lng: -82.4 }),
  project_b: project({ id: 4, name: 'Lakeland tap', utility: 'Keystone Electric', lat: 28, lng: -82 }),
  miles: 4,
  overlap_days: 400,
  overlap_ratio: 0.9,
  window_start: '2025-01-01',
  scores: { ...near.scores, composite: 0.8 },
})

describe('pairEnds', () => {
  it('spans the closest points when the API sends them, else the two markers', () => {
    expect(pairEnds(near)).toEqual([
      [39.8, -76.98],
      [39.58, -77.0],
    ])
    const link: [number, number][] = [
      [39.7, -76.99],
      [39.7, -76.99],
    ]
    expect(pairEnds(pair({ link }))).toEqual(link)
  })
})

describe('utility scope', () => {
  const all = ['A', 'B', 'C']

  it('asks for every pair unless some utilities are hidden', () => {
    expect(pairScope(all, new Set())).toBeUndefined()
    expect(pairScope(all, new Set(['C']))).toEqual(['A', 'B'])
    expect(pairScope(all, new Set(all))).toEqual([]) // nothing shown: nothing to fetch
  })

  it('falls back to every pair when too many utilities are shown to list', () => {
    const many = Array.from({ length: 100 }, (_, i) => `U${i}`)
    expect(pairScope(many, new Set(['U0']))).toBeUndefined()
  })

  it('scopes review projects by utility and search text', () => {
    const projects = [near.project_a, near.project_b, far.project_a]
    const hidden = new Set(['Gulf Power'])
    expect(filterProjects(projects, { query: '', hiddenUtilities: hidden })).toHaveLength(2)
    expect(filterProjects(projects, { query: 'westminster', hiddenUtilities: hidden })).toEqual([
      near.project_b,
    ])
  })
})

describe('compareRank', () => {
  it('puts a closer tier ahead of a higher score', () => {
    const closeLowScore = pair({ id: '5-6', tier: 1, scores: { ...near.scores, composite: 0.2 } })
    const farHighScore = pair({ id: '7-8', tier: 3, scores: { ...near.scores, composite: 0.9 } })
    expect(sortPairs([farHighScore, closeLowScore], 'score')).toEqual([closeLowScore, farHighScore])
  })
})

describe('filterPairs', () => {
  it('matches search text against either project', () => {
    const none = new Set<string>()
    expect(filterPairs([near, far], { query: 'westminster', hiddenUtilities: none })).toEqual([near])
    expect(filterPairs([near, far], { query: 'gulf', hiddenUtilities: none })).toEqual([far])
    expect(filterPairs([near, far], { query: '  ', hiddenUtilities: none })).toHaveLength(2)
  })

  it('uses the server matches for the text once they arrive', () => {
    const none = new Set<string>()
    // "33157" matches no project text, but the server placed project 4 near that ZIP.
    expect(filterPairs([near, far], { query: '33157', hiddenUtilities: none })).toEqual([])
    expect(
      filterPairs([near, far], { query: '33157', hiddenUtilities: none, matchIds: new Set([4]) }),
    ).toEqual([far])
    // Cleared text shows everything, whatever the last server answer was.
    expect(
      filterPairs([near, far], { query: '', hiddenUtilities: none, matchIds: new Set([4]) }),
    ).toHaveLength(2)
  })

  it('drops pairs touching a hidden utility', () => {
    const hidden = new Set(['Chesapeake Power'])
    expect(filterPairs([near, far], { query: '', hiddenUtilities: hidden })).toEqual([far])
  })
})

describe('pairsInView', () => {
  it('keeps pairs with either project inside the map view', () => {
    const pa = { south: 39.7, west: -77.5, north: 40, east: -76.5 } // Hanover only
    expect(pairsInView([near, far], pa)).toEqual([near])
    expect(pairsInView([near, far], null)).toHaveLength(2)
  })

  it('keeps pairs that have no location at all', () => {
    const unplaced = pair({
      project_a: project({ lat: null, lng: null }),
      project_b: project({ id: 2, lat: null, lng: null }),
    })
    expect(pairsInView([unplaced], { south: 0, west: 0, north: 1, east: 1 })).toEqual([unplaced])
  })
})

describe('sortPairs', () => {
  it('orders by the chosen key without mutating the input', () => {
    const input = [near, far]
    expect(sortPairs(input, 'score').map((p) => p.id)).toEqual(['3-4', '1-2'])
    expect(sortPairs(input, 'distance').map((p) => p.id)).toEqual(['3-4', '1-2'])
    expect(sortPairs(input, 'start').map((p) => p.id)).toEqual(['3-4', '1-2'])
    expect(sortPairs(input, 'overlap').map((p) => p.id)).toEqual(['3-4', '1-2'])
    expect(input.map((p) => p.id)).toEqual(['1-2', '3-4'])
  })

  it('sorts by share of build time, then nearest in-service dates, undated last', () => {
    const apart = (id: string, gap: number) =>
      pair({ id, overlap_days: 0, overlap_ratio: 0, time_gap_days: gap, window_start: null })
    const undated = pair({ id: 'u', overlap_ratio: null, time_gap_days: null })
    const got = sortPairs([undated, apart('far', 900), near, apart('soon', 30), far], 'overlap')
    expect(got.map((p) => p.id)).toEqual(['3-4', '1-2', 'soon', 'far', 'u'])
  })
})

describe('bestPairFor', () => {
  it('picks the highest-scoring pair a project is in', () => {
    const also = pair({ id: '1-9', scores: { ...near.scores, composite: 0.95 } })
    expect(bestPairFor(project(), [near, also, far])?.id).toBe('1-9')
    expect(bestPairFor(project({ id: 99 }), [near])).toBeNull()
  })

})
