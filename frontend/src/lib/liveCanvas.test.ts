import { describe, expect, it, vi } from 'vitest'

import { ScaledRedrawCanvas, applyZoomStyle } from './liveCanvas'

describe('applyZoomStyle', () => {
  it('sizes a circle for the zoom from its zoomStyle', () => {
    const layer = {
      options: { weight: 1, zoomStyle: (z: number) => ({ radius: z, weight: z / 10 }) },
      _radius: 1,
    }
    applyZoomStyle(layer, 7)
    expect(layer._radius).toBe(7)
    expect(layer.options.weight).toBe(0.7)
  })

  it('leaves paths without one alone', () => {
    const layer = { options: { weight: 2 }, _radius: 3 }
    applyZoomStyle(layer, 7)
    expect(layer).toEqual({ options: { weight: 2 }, _radius: 3 })
  })
})

describe('ScaledRedrawCanvas', () => {
  it('draws lines and dashes at their normal width while the frame is scaled up', () => {
    const canvas = new ScaledRedrawCanvas() as unknown as {
      _drawScale: number
      _fillStroke(ctx: unknown, layer: unknown): void
    }
    const drawn: { lineWidth: number; dash: number[] }[] = []
    const ctx = {
      lineWidth: 0,
      setLineDash: vi.fn(),
      stroke() {
        drawn.push({ lineWidth: this.lineWidth, dash: this.setLineDash.mock.lastCall![0] })
      },
    }
    const options = { stroke: true, weight: 2, _dashArray: [6, 3] }
    const layer = { options }

    canvas._drawScale = 4
    canvas._fillStroke(ctx, layer)
    canvas._drawScale = 1
    canvas._fillStroke(ctx, layer)

    expect(drawn).toEqual([
      { lineWidth: 0.5, dash: [1.5, 0.75] },
      { lineWidth: 2, dash: [6, 3] },
    ])
    expect(options).toEqual({ stroke: true, weight: 2, _dashArray: [6, 3] })
  })
})
