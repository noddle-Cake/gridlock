import { describe, expect, it } from 'vitest'

import { windowScale } from './buildWindows'

describe('windowScale', () => {
  it('places both windows on one padded axis, in order', () => {
    const scale = windowScale([
      ['2025-01-01', '2025-12-31'],
      ['2026-01-01', '2026-12-31'],
    ])!
    const a = scale.place(['2025-01-01', '2025-12-31'])
    const b = scale.place(['2026-01-01', '2026-12-31'])
    expect(a.left).toBeGreaterThan(0)
    expect(b.left + b.width).toBeLessThan(100)
    expect(a.left + a.width).toBeCloseTo(b.left, 5) // back to back, no gap
    expect(a.width).toBeCloseTo(b.width, 0)
    expect(scale.years.map((y) => y.year)).toEqual([2025, 2026, 2027])
  })

  it('thins year labels on long axes and skips missing windows', () => {
    const scale = windowScale([['2023-12-31', '2024-12-31'], null, ['2032-06-01', '2033-06-01']])!
    const years = scale.years.map((y) => y.year)
    expect(years.length).toBeLessThanOrEqual(6)
    expect(years[1] - years[0]).toBe(2)
    expect(windowScale([null, undefined])).toBeNull()
  })
})
