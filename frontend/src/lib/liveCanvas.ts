import L from 'leaflet'

// Leaflet's canvas renderer does nothing between the start and end of a zoom but stretch its
// last frame with a CSS transform, so a fly across several levels blows lines and dots up
// many times over and snaps them back on arrival. These renderers draw every frame instead.
// Both lean on Leaflet 1.9 internals (the underscored members), like smoothWheelZoom does.

/** Circle size at a zoom. Set as `zoomStyle` in a CircleMarker's path options. */
export type ZoomStyle = (zoom: number) => { radius: number; weight: number }

interface StyledLayer {
  options: L.PathOptions & { zoomStyle?: ZoomStyle }
  _radius?: number
}

/** Size a circle for `zoom` from its `zoomStyle`, if it has one. */
export function applyZoomStyle(layer: StyledLayer, zoom: number): void {
  const style = layer.options.zoomStyle?.(zoom)
  if (!style) return
  layer._radius = style.radius
  layer.options.weight = style.weight
}

type CanvasClass = new (options?: L.RendererOptions) => L.Canvas

interface CanvasInternals {
  _map: L.Map
  _layers: Record<string, StyledLayer>
  _onZoomEnd(): void
  _update(): void
}

const canvasProto = L.Canvas.prototype as unknown as {
  _onZoomEnd(this: unknown): void
  _initPath(this: unknown, layer: StyledLayer): void
  _updatePath(this: unknown, layer: StyledLayer): void
  _fillStroke(this: unknown, ctx: CanvasRenderingContext2D, layer: StyledLayer): void
}

/**
 * For the project markers and connectors: a few thousand points, so every frame of a zoom
 * reprojects and redraws them all. Circles with a `zoomStyle` are sized for the zoom as they
 * are drawn, so they grow and shrink with the map without a React render per frame.
 */
export const LiveZoomCanvas: CanvasClass = L.Canvas.extend({
  _onZoom(this: CanvasInternals) {
    this._onZoomEnd()
    this._update()
  },
  _onZoomEnd(this: CanvasInternals) {
    const zoom = this._map.getZoom()
    for (const id in this._layers) applyZoomStyle(this._layers[id], zoom)
    canvasProto._onZoomEnd.call(this)
  },
  // A circle being added, or restyled by react-leaflet, keeps its size for the current zoom.
  _initPath(this: CanvasInternals, layer: StyledLayer) {
    if (this._map) applyZoomStyle(layer, this._map.getZoom())
    canvasProto._initPath.call(this, layer)
  },
  _updatePath(this: CanvasInternals, layer: StyledLayer) {
    applyZoomStyle(layer, this._map.getZoom())
    canvasProto._updatePath.call(this, layer)
  },
})

interface ShapeLayer extends StyledLayer {
  getBounds?(): L.LatLngBounds
  _parts: unknown[]
  _project(): void
  _update(): void
}

/**
 * Below this zoom most of the country is in view, and reprojecting it all would stall the
 * frame (~50-80 ms). Outlines that coarse can stretch 4x without looking blocky.
 */
const REPROJECT_MIN_ZOOM = 5

const rendererUpdate = (L.Renderer.prototype as unknown as { _update(this: unknown): void })
  ._update

interface ScaledInternals {
  _map: L.Map & { _getNewPixelOrigin(center: L.LatLng, zoom: number): L.Point }
  _container: HTMLCanvasElement
  _ctx: CanvasRenderingContext2D
  _center: L.LatLng
  _zoom: number
  _bounds: L.Bounds
  _redrawBounds: L.Bounds | null
  _drawScale: number
  _layers: Record<string, ShapeLayer>
  options: { padding: number }
  _draw(): void
  _reprojectInView(): void
}

/**
 * For the base map: half a million points is too many to reproject every frame, so each
 * frame redraws the shapes as last projected, scaled by the canvas transform the way the
 * stretch did, but with line widths and dashes divided by that scale. Areas grow with the
 * map while borders keep their width. Past 2x the outlines, simplified for the old zoom,
 * would turn blocky (and zooming out, stop covering the view), so from REPROJECT_MIN_ZOOM up
 * the shapes in view are reprojected each level; lines come in short pieces (chunkLines) so
 * that is a few states' worth. Everything is reprojected when the zoom ends, as before.
 */
export const ScaledRedrawCanvas: CanvasClass = L.Canvas.extend({
  _onZoom(this: ScaledInternals) {
    const map = this._map
    const zoom = map.getZoom()
    const drift = zoom - this._zoom
    // Zooming out, the canvas (1.6x the view) stops covering it 0.7 levels out.
    if (zoom >= REPROJECT_MIN_ZOOM && (drift >= 1 || drift <= -0.6)) this._reprojectInView()
    const center = map.getCenter()
    const scale = map.getZoomScale(zoom, this._zoom)
    // Where Leaflet would put the stretched canvas's top-left (Renderer._updateTransform).
    const offset = map
      .getSize()
      .multiplyBy(0.5 + this.options.padding)
      .multiplyBy(-scale)
      .add(map.project(this._center, zoom))
      .subtract(map._getNewPixelOrigin(center, zoom))
    // Keep the canvas unstretched over the current view instead, and draw into it.
    const min = map
      .containerPointToLayerPoint(map.getSize().multiplyBy(-this.options.padding))
      .round()
    L.DomUtil.setPosition(this._container, min)
    const drawn = this._bounds.min! // the canvas's top-left when the shapes were last drawn
    const ratio = L.Browser.retina ? 2 : 1
    const ctx = this._ctx
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, this._container.width, this._container.height)
    ctx.setTransform(
      ratio * scale,
      0,
      0,
      ratio * scale,
      ratio * (offset.x - min.x - scale * drawn.x),
      ratio * (offset.y - min.y - scale * drawn.y),
    )
    this._redrawBounds = null
    this._drawScale = scale
    this._draw()
    this._drawScale = 1
  },
  _reprojectInView(this: ScaledInternals) {
    rendererUpdate.call(this) // bounds, centre and zoom of the current view; draws nothing
    const view = this._map.getBounds().pad(this.options.padding)
    const zoom = this._map.getZoom()
    for (const id in this._layers) {
      const layer = this._layers[id]
      const minZoom = (layer.options as { minZoom?: number }).minZoom ?? -Infinity
      if (zoom < minZoom || (layer.getBounds && !view.intersects(layer.getBounds()))) {
        // Off screen, or detail about to be removed: skipped until the zoom ends.
        layer._parts = []
        continue
      }
      layer._project()
      layer._update() // clip and simplify; drawing waits for _draw
    }
  },
  _fillStroke(this: ScaledInternals, ctx: CanvasRenderingContext2D, layer: StyledLayer) {
    const scale = this._drawScale || 1
    if (scale === 1) return canvasProto._fillStroke.call(this, ctx, layer)
    const o = layer.options as L.PathOptions & { _dashArray?: number[] }
    const { weight, _dashArray: dashes } = o
    o.weight = (weight ?? 0) / scale
    if (dashes) o._dashArray = dashes.map((d) => d / scale)
    canvasProto._fillStroke.call(this, ctx, layer)
    o.weight = weight
    o._dashArray = dashes
  },
})
