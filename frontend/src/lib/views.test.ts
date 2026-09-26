import { describe, expect, it } from 'vitest'

import { project } from '../test/fixtures'
import { diffDraft, toDraft } from './draft'
import { dateLabel, gapLabel, rangeLabel, timingLabel, usdRange, utilityColors } from './format'
import { markerStyle } from './mapStyle'
import { timelineItems } from './timelineItems'

describe('markerStyle (Req 9.1, 9.3, 9.4)', () => {
  it('highlights paired projects', () => {
    const plain = markerStyle(project(), '#f00', { paired: false, selected: false })
    const paired = markerStyle(project(), '#f00', { paired: true, selected: false })
    expect(paired.radius).toBeGreaterThan(plain.radius)
    expect(paired.weight!).toBeGreaterThan(plain.weight!)
    expect(paired.fillOpacity!).toBeGreaterThan(plain.fillOpacity!)
  })

  it('draws approximate locations hollow and dashed', () => {
    const approx = markerStyle(project({ approximate: true }), '#f00', {
      paired: true,
      selected: false,
    })
    const exact = markerStyle(project(), '#f00', { paired: true, selected: false })
    expect(approx.dashArray).toBeTruthy()
    expect(exact.dashArray).toBeUndefined()
    expect(approx.fillOpacity!).toBeLessThan(0.2)
  })
})

describe('timelineItems (Req 9.2)', () => {
  it('positions each project by its start and (inclusive) end date', () => {
    const [item] = timelineItems([project()], new Set([1]), new Set(), { 'Keystone Electric': '#f00' })
    expect(item.start).toBe('2026-04-01')
    expect(item.end).toBe('2026-10-01') // vis ranges are end-exclusive
    expect(item.group).toBe('Keystone Electric')
    expect(item.className).toContain('tl-paired')
    expect(item.title).toContain('Q2 2026 – Q3 2026')
  })

  it('handles single-sided dates and skips undated projects', () => {
    const items = timelineItems(
      [project({ id: 1, end_date: null }), project({ id: 2, start_date: null, end_date: null })],
      new Set(),
      new Set(),
      {},
    )
    expect(items).toHaveLength(1)
    expect(items[0].end).toBe('2026-04-02')
  })
})

describe('format helpers', () => {
  it('formats money ranges, schedule gaps and timing', () => {
    expect(usdRange(337_874, 1_013_623)).toBe('$338k–$1.0M')
    expect(usdRange(50_000, 50_000)).toBe('$50k')
    expect(gapLabel(3074)).toBe('8.4 years')
    expect(timingLabel({ overlap_ratio: 0, time_gap_days: 152 })).toBe('in service 5 months apart')
    expect(timingLabel({ overlap_ratio: null, time_gap_days: null })).toBe('schedule unknown')
  })

  it('labels dates at their source precision', () => {
    expect(dateLabel('2026-04-01', 'quarter')).toBe('Q2 2026')
    expect(dateLabel('2027-01-01', 'year')).toBe('2027')
    expect(dateLabel('2026-05-01', 'month')).toBe('May 2026')
    expect(dateLabel('2026-05-07', 'day')).toBe('May 7, 2026')
    expect(rangeLabel('2027-01-01', null, 'year', null)).toBe('2027')
    expect(rangeLabel(null, null, null, null)).toBe('—')
  })

  it('assigns stable colors regardless of order', () => {
    expect(utilityColors(['B', 'A'])).toEqual(utilityColors(['A', 'B', 'A']))
  })
})

describe('diffDraft', () => {
  it('sends only changed fields and edits lat/lng together', () => {
    const p = project()
    const d = { ...toDraft(p), name: 'New', lat: '40.1' }
    expect(diffDraft(p, d)).toEqual({ name: 'New', lat: 40.1, lng: -76.98 })
    expect(diffDraft(p, toDraft(p))).toEqual({})
  })
})
