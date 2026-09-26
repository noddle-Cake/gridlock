import type { LatLng, Map as LeafletMap, Point } from 'leaflet'

// Leaflet's built-in scrollWheelZoom snaps to zoomSnap and runs a 250ms CSS animation per
// step, dropping any wheel events that arrive mid-animation — trackpad pinches feel blocky.
// This handler instead eases toward a target zoom every frame via the same internal
// `_move(..., { pinch: true })` path Leaflet's touch pinch uses, so tiles and SVG layers are
// transformed continuously and only re-rendered once the gesture settles.

interface MapInternals {
  _move(center: LatLng, zoom: number, data?: { pinch?: boolean; round?: boolean }): void
  _moveStart(zoomChanged: boolean, noMoveStart: boolean): void
  _moveEnd(zoomChanged: boolean): void
  _stop(): void
  _animatingZoom?: boolean
}

/** Zoom levels a single pinch step spans before clamping, to tame runaway deltas. */
const MAX_STEP = 2
/** Time constant (ms) for easing the rendered zoom toward the target. */
const EASE_MS = 45

/**
 * Convert a wheel event into a zoom-level change (positive = zoom in).
 * Trackpad pinches arrive as ctrl+wheel with deltaY = -100·ln(scale) in Chromium/Firefox,
 * so dividing by 100·ln2 makes the map follow the fingers 1:1. Plain wheel/scroll gets
 * about one zoom level per mouse-wheel notch.
 */
export function wheelZoomDelta(e: Pick<WheelEvent, 'deltaY' | 'deltaMode' | 'ctrlKey'>): number {
  let px = e.deltaY
  if (e.deltaMode === 1) px *= 16
  else if (e.deltaMode === 2) px *= 800
  const dz = e.ctrlKey ? -px / (100 * Math.LN2) : -px / 100
  return Math.max(-MAX_STEP, Math.min(MAX_STEP, dz))
}

/** Attach smooth wheel/trackpad zoom to `map`; returns a cleanup function. */
export function enableSmoothWheelZoom(map: LeafletMap): () => void {
  const m = map as LeafletMap & MapInternals
  const container = map.getContainer()
  let frame = 0
  let lastTime = 0
  let zoom = 0
  let goal = 0
  let anchor: Point | null = null

  function centerAround(point: Point, toZoom: number): LatLng {
    // Same math as Map.setZoomAround: keep the latlng under `point` fixed.
    const scale = map.getZoomScale(toZoom, map.getZoom())
    const half = map.getSize().divideBy(2)
    const offset = point.subtract(half).multiplyBy(1 - 1 / scale)
    return map.containerPointToLatLng(half.add(offset))
  }

  function step(now: number) {
    const dt = Math.min(now - lastTime, 64)
    lastTime = now
    const diff = goal - zoom
    zoom = Math.abs(diff) < 1e-3 ? goal : zoom + diff * (1 - Math.exp(-dt / EASE_MS))
    m._move(centerAround(anchor!, zoom), zoom, { pinch: true, round: false })
    if (zoom === goal) {
      frame = 0
      m._moveEnd(true)
    } else {
      frame = requestAnimationFrame(step)
    }
  }

  function onWheel(e: WheelEvent) {
    e.preventDefault()
    e.stopPropagation()
    if (m._animatingZoom) return // let a button/keyboard zoom animation finish

    if (!frame) {
      m._stop() // cancel any in-flight flyTo/pan
      zoom = goal = map.getZoom()
      m._moveStart(true, false)
      lastTime = performance.now()
      frame = requestAnimationFrame(step)
    }
    anchor = map.mouseEventToContainerPoint(e)
    goal = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), goal + wheelZoomDelta(e)))
  }

  container.addEventListener('wheel', onWheel, { passive: false })
  return () => {
    container.removeEventListener('wheel', onWheel)
    if (frame) {
      cancelAnimationFrame(frame)
      frame = 0
      m._moveEnd(true)
    }
  }
}
