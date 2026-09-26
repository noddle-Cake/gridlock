import fc from 'fast-check'
import { describe, expect, it } from 'vitest'

import { DEFAULT_CONFIDENCE_THRESHOLD, needsReview } from './review'

const unit = fc.double({ min: 0, max: 1, noNaN: true })

describe('needsReview', () => {
  // Feature: gridmerge, Property 17: Review predicate matches the threshold boundary
  // (Requirements 3.3 / 13.1 flag confidence "equal to or below" the threshold.)
  it('flags exactly the projects at or below the threshold', () => {
    fc.assert(
      fc.property(unit, unit, (confidence, threshold) => {
        expect(needsReview(confidence, threshold)).toBe(confidence <= threshold)
      }),
      { numRuns: 200 },
    )
  })

  it('is monotone: lower confidence never needs less review', () => {
    fc.assert(
      fc.property(unit, unit, unit, (a, b, t) => {
        const [lo, hi] = a <= b ? [a, b] : [b, a]
        if (needsReview(hi, t)) expect(needsReview(lo, t)).toBe(true)
      }),
      { numRuns: 200 },
    )
  })

  it('uses 0.7 by default and includes the boundary', () => {
    expect(DEFAULT_CONFIDENCE_THRESHOLD).toBe(0.7)
    expect(needsReview(0.7, 0.7)).toBe(true)
    expect(needsReview(0.71, 0.7)).toBe(false)
  })
})
