import { describe, expect, it } from 'vitest'

import type { LineCollection, LineFeature } from '../types'
import { lineBounds, lineOwners, lineStyle, lineTooltip, lineWeight } from './lines'

function line(id: string, owner: string | null, kv: number | null = 115): LineFeature {
  return {
    type: 'Feature',
    id,
    geometry: {
      type: 'MultiLineString',
      coordinates: [
        [
          [-84.2, 30.9],
          [-84.1, 30.8],
        ],
      ],
    },
    properties: {
      owner: owner ? owner.toUpperCase() + ' CO' : null,
      owner_norm: owner,
      voltage_kv: kv,
      volt_class: null,
      status: 'IN SERVICE',
      sub_1: 'THOMASVILLE',
      sub_2: 'TAP143132',
    },
  }
}

const fc = (features: LineFeature[]): LineCollection => ({ type: 'FeatureCollection', features })

describe('reference line helpers', () => {
  it('weights lines by voltage', () => {
    expect([null, 69, 115, 230, 500].map(lineWeight)).toEqual([1, 1, 1.5, 2.2, 3])
  })

  it('colors by owner and dashes unknown owners', () => {
    expect(lineStyle(line('1', 'JEA'), { JEA: '#123456' }).color).toBe('#123456')
    const unknown = lineStyle(line('2', null), {})
    expect(unknown.dashArray).toBeDefined()
  })

  it('counts owners, biggest first, unknown last', () => {
    const owners = lineOwners(
      fc([line('1', null), line('2', 'JEA'), line('3', 'Georgia Power'), line('4', 'Georgia Power')]),
    )
    expect(owners).toEqual([
      { owner: 'Georgia Power', count: 2 },
      { owner: 'JEA', count: 1 },
      { owner: null, count: 1 },
    ])
  })

  it('escapes tooltip text and hides placeholder substation ids', () => {
    const f = line('1', '<b>Evil</b>')
    const html = lineTooltip(f)
    expect(html).not.toContain('<b>')
    expect(html).toContain('THOMASVILLE')
    expect(html).not.toContain('TAP143132')
  })

  it('bounds every coordinate', () => {
    expect(lineBounds(fc([line('1', 'JEA')]))).toEqual([
      [30.8, -84.2],
      [30.9, -84.1],
    ])
    expect(lineBounds(fc([]))).toBeNull()
  })
})
