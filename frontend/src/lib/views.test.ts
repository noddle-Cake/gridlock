import fc from 'fast-check'
import { describe, expect, it } from 'vitest'

import { project } from '../test/fixtures'
import { diffDraft, toDraft } from './draft'
import {
  OTHER_COLOR,
  PALETTE,
  bothBuildingLabel,
  dateLabel,
  durationLabel,
  gapLabel,
  num,
  plural,
  rangeLabel,
  rulesLabel,
  timingLabel,
  usdRange,
  utilityColors,
} from './format'
import { colorLegend, highlightSize, markerScale, markerStyle, projectColor } from './mapStyle'
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

  it('shrinks the selected pair with the view but keeps it above its neighbours', () => {
    const at = (zoom: number, paired: boolean, selected: boolean) =>
      markerStyle(project(), '#f00', { paired, selected }, zoom).radius
    expect(at(4, false, true)).toBeLessThan(at(10, false, true))
    for (const zoom of [3, 5, 6.5, 8, 11]) {
      expect(at(zoom, false, true)).toBeGreaterThan(at(zoom, true, false))
    }
    expect(highlightSize(4.5).radius).toBeLessThan(highlightSize(5).radius)
  })

  it('resizes markers smoothly as the map zooms, with no jumps', () => {
    for (const state of [
      { paired: false, selected: false },
      { paired: true, selected: false },
      { paired: false, selected: true },
    ]) {
      let prev = markerStyle(project(), '#f00', state, 3)
      for (let zoom = 3.05; zoom <= 12; zoom += 0.05) {
        const next = markerStyle(project(), '#f00', state, zoom)
        expect(Math.abs(next.radius - prev.radius)).toBeLessThan(0.1)
        expect(Math.abs(next.weight - prev.weight)).toBeLessThan(0.1)
        prev = next
      }
    }
    expect(markerScale(3)).toBe(0.5)
    expect(markerScale(7)).toBe(1)
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

  it('separates thousands in counts and pluralizes their nouns', () => {
    expect(num(0)).toBe('0')
    expect(num(999)).toBe('999')
    expect(num(1884)).toBe('1,884')
    expect(num(1_234_567)).toBe('1,234,567')
    expect(plural(1, 'project')).toBe('1 project')
    expect(plural(0, 'project')).toBe('0 projects')
    expect(plural(1706, 'result')).toBe('1,706 results')
    expect(plural(2, 'utility', 'utilities')).toBe('2 utilities')
    fc.assert(
      fc.property(fc.nat(), (n) => {
        expect(num(n).replaceAll(',', '')).toBe(String(n))
        expect(num(n)).toMatch(/^\d{1,3}(,\d{3})*$/)
      }),
    )
  })

  it('says how long two projects build together, and when', () => {
    expect(durationLabel(30)).toBe('4 weeks')
    expect(durationLabel(213)).toBe('7 months')
    expect(durationLabel(730)).toBe('2.0 years')
    expect(bothBuildingLabel({ window_start: '2026-04-01', window_end: '2026-10-30' })).toBe(
      'Both building Apr 2026 – Oct 2026',
    )
    expect(rulesLabel('2026-09-26', 30)).toContain('in service from Sep 26, 2026')
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

  it('colors only the busiest companies and never reuses a hue', () => {
    // 20 companies; "Big" has the most projects.
    const names = ['Big', 'Big', 'Big', ...Array.from({ length: 19 }, (_, i) => `Co ${i}`)]
    const colors = utilityColors(names)
    expect(Object.keys(colors)).toHaveLength(PALETTE.length)
    expect(colors.Big).toBeDefined()
    expect(new Set(Object.values(colors)).size).toBe(PALETTE.length)
  })

  it('gives the utilities on screen the leading, most distinct slots', () => {
    // Alphabetically among the busiest, the challenge pair would get slots 1 and 3 (two
    // oranges); shown first they get blue and orange.
    const names = ['AEP', 'AEP', 'Dominion Energy South Carolina', 'Duke', 'Georgia Power', 'Duke']
    const colors = utilityColors(names, ['Georgia Power', 'Dominion Energy South Carolina'])
    expect(colors['Dominion Energy South Carolina']).toBe(PALETTE[0])
    expect(colors['Georgia Power']).toBe(PALETTE[1])
    expect(colors.AEP).toBeDefined()
    expect(new Set(Object.values(colors)).size).toBe(Object.keys(colors).length)
  })
})

describe('project color encodings', () => {
  const gen = project({ id: 1, type: 'generation', utility: 'A', start_date: '2026-03-01' })
  const line = project({ id: 2, type: 'transmission line', utility: 'B', start_date: '2031-01-01' })
  const bare = project({ id: 3, type: null, utility: 'C', start_date: null, end_date: null })
  const colors = { A: '#123456' }

  it('colors by type, company (top-N or other) and start year', () => {
    expect(projectColor(gen, 'type', colors)).not.toBe(projectColor(line, 'type', colors))
    expect(projectColor(bare, 'type', colors)).toBe(OTHER_COLOR)
    expect(projectColor(gen, 'utility', colors)).toBe('#123456')
    expect(projectColor(line, 'utility', colors)).toBe(OTHER_COLOR)
    expect(projectColor(gen, 'year', colors)).not.toBe(projectColor(line, 'year', colors))
    expect(projectColor(bare, 'year', colors)).toBe(OTHER_COLOR)
  })

  it('builds a legend with counts and an "other" row, dropping empty categories', () => {
    expect(colorLegend([gen, line, bare], 'type', colors)).toEqual([
      { label: 'Generation', color: projectColor(gen, 'type', colors), count: 1 },
      { label: 'Transmission line', color: projectColor(line, 'type', colors), count: 1 },
      { label: 'Type unknown', color: OTHER_COLOR, count: 1 },
    ])
    const byCompany = colorLegend([gen, line, bare], 'utility', colors)
    expect(byCompany.map((r) => [r.label, r.count])).toEqual([
      ['A', 1],
      ['Other (2 companies)', 2],
    ])
    const byYear = colorLegend([gen, line, bare], 'year', colors).map((r) => r.label)
    expect(byYear).toEqual(['2026 or earlier', '2030+', 'Undated'])
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
