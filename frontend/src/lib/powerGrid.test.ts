import type { VectorTileFeature } from '@mapbox/vector-tile'
import { describe, expect, it } from 'vitest'

import {
  LOW_VOLTAGE_COLOR,
  drawPowerTile,
  featureVoltage,
  lineWidth,
  voltageColor,
} from './powerGrid'

describe('voltageColor', () => {
  it('buckets by lower bound', () => {
    expect(voltageColor(500)).toBe('#B54EB2')
    expect(voltageColor(230)).toBe('#C73030')
    expect(voltageColor(220)).toBe('#C73030')
    expect(voltageColor(115)).toBe('#B59F10')
    expect(voltageColor(69)).toBe('#B59F10')
    expect(voltageColor(13.8)).toBe('#6E97B8')
  })

  it('falls back to grey for low or unknown voltage', () => {
    expect(voltageColor(4)).toBe(LOW_VOLTAGE_COLOR)
    expect(voltageColor(null)).toBe(LOW_VOLTAGE_COLOR)
  })
})

describe('featureVoltage', () => {
  it('takes the highest circuit voltage', () => {
    expect(featureVoltage({ voltage: 115, voltage_2: 230 })).toBe(230)
  })

  it('ignores missing and non-numeric values', () => {
    expect(featureVoltage({ voltage: 'unknown' })).toBeNull()
    expect(featureVoltage({})).toBeNull()
  })
})

describe('lineWidth', () => {
  it('is heavier for higher voltage and grows with zoom', () => {
    expect(lineWidth(500, 9)).toBeGreaterThan(lineWidth(69, 9))
    expect(lineWidth(69, 9)).toBeGreaterThan(lineWidth(null, 9))
    expect(lineWidth(230, 12)).toBeGreaterThan(lineWidth(230, 7))
  })
})

function feature(
  properties: Record<string, number | string | boolean>,
  geom: [number, number][],
): VectorTileFeature {
  return {
    properties,
    extent: 4096,
    loadGeometry: () => [geom.map(([x, y]) => ({ x, y }))],
  } as unknown as VectorTileFeature
}

function tile(layers: Record<string, VectorTileFeature[]>) {
  return {
    layers: Object.fromEntries(
      Object.entries(layers).map(([name, fs]) => [
        name,
        { length: fs.length, feature: (i: number) => fs[i] },
      ]),
    ),
  } as never
}

/** Canvas stand-in that logs the stroke colour of every stroke() call. */
function recorder() {
  const strokes: string[] = []
  const ctx = {
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 1,
    globalAlpha: 1,
    lineCap: 'butt',
    lineJoin: 'miter',
    moves: [] as [number, number][],
    beginPath() {},
    moveTo(x: number, y: number) {
      ctx.moves.push([x, y])
    },
    lineTo() {},
    closePath() {},
    arc() {},
    rect() {},
    fill() {},
    stroke() {
      strokes.push(String(ctx.strokeStyle))
    },
    setLineDash() {},
  }
  return { ctx, strokes }
}

describe('drawPowerTile', () => {
  const line = (kv: number, extra = {}) =>
    feature({ voltage: kv, ...extra }, [
      [0, 0],
      [4096, 4096],
    ])

  it('draws lower-voltage lines first so the backbone sits on top', () => {
    const { ctx, strokes } = recorder()
    drawPowerTile(ctx as never, tile({ power_line: [line(500), line(13.8), line(230)] }), 9, 256)
    expect(strokes).toEqual([voltageColor(13.8), voltageColor(230), voltageColor(500)])
  })

  it('scales tile coordinates to the canvas size', () => {
    const { ctx } = recorder()
    const sub = feature({}, [[2048, 1024]])
    drawPowerTile(ctx as never, tile({ power_line: [line(69)], power_substation_point: [sub] }), 9, 256)
    expect(ctx.moves[0]).toEqual([0, 0])
  })

  it('hides substation busbars until zoomed in', () => {
    const tiles = () => tile({ power_line: [line(115, { line: 'busbar' }), line(230)] })
    const far = recorder()
    drawPowerTile(far.ctx as never, tiles(), 9, 256)
    expect(far.strokes).toHaveLength(1)
    const near = recorder()
    drawPowerTile(near.ctx as never, tiles(), 14, 256)
    expect(near.strokes).toHaveLength(2)
  })
})
