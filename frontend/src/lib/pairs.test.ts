import { describe, expect, it } from 'vitest'

import { pair, project } from '../test/fixtures'
import { bestPairFor, filterPairs, pairsInView, scoreBand, sortPairs } from './pairs'

const near = pair()
const far = pair({
  id: '3-4',
  project_a: project({ id: 3, name: 'Tampa bank', utility: 'Gulf Power', lat: 27.9, lng: -82.4 }),
  project_b: project({ id: 4, name: 'Lakeland tap', utility: 'Keystone Electric', lat: 28, lng: -82 }),
  miles: 4,
  overlap_days: 400,
  window_start: '2025-01-01',
  scores: { ...near.scores, composite: 0.8 },
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
    expect(sortPairs([far, near], 'overlap').map((p) => p.id)).toEqual(['3-4', '1-2'])
    expect(input.map((p) => p.id)).toEqual(['1-2', '3-4'])
  })
})

describe('bestPairFor / scoreBand', () => {
  it('picks the highest-scoring pair a project is in', () => {
    const also = pair({ id: '1-9', scores: { ...near.scores, composite: 0.95 } })
    expect(bestPairFor(project(), [near, also, far])?.id).toBe('1-9')
    expect(bestPairFor(project({ id: 99 }), [near])).toBeNull()
  })

  it('bands composite scores', () => {
    expect(scoreBand(0.8)).toBe('high')
    expect(scoreBand(0.5)).toBe('mid')
    expect(scoreBand(0.2)).toBe('low')
  })
})
