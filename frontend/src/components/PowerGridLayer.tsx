import { VectorTile } from '@mapbox/vector-tile'
import L from 'leaflet'
import { PbfReader } from 'pbf'
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'

import {
  POWER_ATTRIBUTION,
  POWER_MAX_NATIVE_ZOOM,
  POWER_MIN_ZOOM,
  POWER_TILES_URL,
  drawPowerTile,
} from '../lib/powerGrid'

/** Canvas grid layer that fetches, decodes and paints the power-infrastructure vector tiles. */
class PowerGridTiles extends L.GridLayer {
  private requests = new WeakMap<HTMLElement, AbortController>()

  constructor() {
    super({
      attribution: POWER_ATTRIBUTION,
      minZoom: POWER_MIN_ZOOM,
      // Without a maxZoom GridLayer computes each zoom level's z-index as NaN, so a stretched
      // parent level kept during loading isn't stacked under the sharp current one.
      maxZoom: 24,
      maxNativeZoom: POWER_MAX_NATIVE_ZOOM,
      // Flying to a pair crosses several zoom levels; fetch and decode tiles only for the
      // level it lands on, not every one it passes.
      updateWhenZooming: false,
    })
    // Cancel downloads for tiles that scrolled away before they arrived.
    this.on('tileunload', (e: L.TileEvent) => this.requests.get(e.tile)?.abort())
  }

  protected createTile(coords: L.Coords, done: L.DoneCallback): HTMLElement {
    const size = this.getTileSize()
    const ratio = window.devicePixelRatio || 1
    const canvas = document.createElement('canvas')
    canvas.width = size.x * ratio
    canvas.height = size.y * ratio

    const controller = new AbortController()
    this.requests.set(canvas, controller)
    const url = L.Util.template(POWER_TILES_URL, { x: coords.x, y: coords.y, z: coords.z })
    fetch(url, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`power tile ${res.status}`)
        return res.arrayBuffer()
      })
      .then((buf) => {
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.scale(ratio, ratio)
          drawPowerTile(ctx, new VectorTile(new PbfReader(buf)), coords.z, size.x)
        }
        done(undefined, canvas)
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') done(err, canvas)
      })
    return canvas
  }
}

export function PowerGridLayer() {
  const map = useMap()
  useEffect(() => {
    const layer = new PowerGridTiles().addTo(map)
    return () => {
      layer.remove()
    }
  }, [map])
  return null
}
