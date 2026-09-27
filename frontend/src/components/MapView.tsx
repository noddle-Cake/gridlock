import 'leaflet/dist/leaflet.css'

import type {
  CircleMarker as LeafletCircleMarker,
  LatLngBoundsExpression,
  LatLngExpression,
  Map as LeafletMap,
  PathOptions,
  Polyline as LeafletPolyline,
} from 'leaflet'
import { memo, type Ref, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Polyline, ScaleControl, Tooltip, useMap } from 'react-leaflet'

import { milesToKm } from '../lib/distanceBands'
import { bothBuildingLabel, durationLabel, escapeHtml as esc, rangeLabel } from '../lib/format'
import {
  COLOR_BY_OPTIONS,
  type ColorBy,
  type LegendEntry,
  highlightSize,
  markerStyle,
} from '../lib/mapStyle'
import { LiveZoomCanvas, type ZoomStyle } from '../lib/liveCanvas'
import { legendStartsOpen } from '../lib/legendLayout'
import { type ViewBounds, pairEnds } from '../lib/pairs'
import { LOW_VOLTAGE_COLOR, VOLTAGE_SCALE } from '../lib/powerGrid'
import { enableSmoothWheelZoom } from '../lib/smoothWheelZoom'
import type { CoordinationPair, Project } from '../types'
import { BaseMap } from './BaseMap'
import { PowerGridLayer } from './PowerGridLayer'

const FIT_MAX_ZOOM = 11

/**
 * Fit options that keep framed projects clear of the legend stack in the top-right corner
 * (it covered the SC side of the DESC ↔ Georgia Power view): the right edge is padded by the
 * stack's width, capped so a narrow map still has room.
 */
function fitOptions(map: LeafletMap) {
  const tools = map.getContainer().parentElement?.querySelector('.map-tools')
  const width = map.getSize().x
  const right = Math.min((tools?.getBoundingClientRect().width ?? 0) + 24, width * 0.4)
  return {
    paddingTopLeft: [40, 40] as [number, number],
    paddingBottomRight: [Math.max(40, right), 40] as [number, number],
    maxZoom: FIT_MAX_ZOOM,
  }
}

/**
 * Frames all projects on load and glides to a pair when one is selected. Leaving the
 * pair returns to wherever the planner was looking before, like closing a listing.
 */
function ViewController({
  allBounds,
  pairBounds,
}: {
  allBounds: LatLngBoundsExpression | null
  pairBounds: LatLngBoundsExpression | null
}) {
  const map = useMap()
  const fitted = useRef(false)
  const prev = useRef<{ all: typeof allBounds; pair: typeof pairBounds }>({ all: null, pair: null })
  const saved = useRef<{ center: LatLngExpression; zoom: number } | 'all' | null>(null)

  useEffect(() => {
    const was = prev.current
    prev.current = { all: allBounds, pair: pairBounds }
    const fit = fitOptions(map)
    const glide = { ...fit, duration: 0.8 }

    if (pairBounds !== was.pair) {
      if (pairBounds) {
        saved.current ??= { center: map.getCenter(), zoom: map.getZoom() }
        map.flyToBounds(pairBounds, glide)
      } else if (saved.current === 'all' || allBounds !== was.all) {
        if (allBounds) map.flyToBounds(allBounds, glide)
        saved.current = null
      } else if (saved.current) {
        map.flyTo(saved.current.center, saved.current.zoom, { duration: 0.8 })
        saved.current = null
      }
      return
    }
    if (!allBounds || allBounds === was.all) return
    if (pairBounds) {
      // Data changed underneath the open pair: refit everything once it closes.
      saved.current = 'all'
      return
    }
    // Snap on first load; glide between views after that.
    if (fitted.current) map.flyToBounds(allBounds, glide)
    else map.fitBounds(allBounds, { ...fit, animate: false })
    fitted.current = true
  }, [map, allBounds, pairBounds])
  return null
}

/** Where a search pick asks the map to go; `seq` makes picking the same place again fly. */
export interface MapFocus {
  bounds: [[number, number], [number, number]]
  seq: number
}

function FocusController({ focus }: { focus: MapFocus | null }) {
  const map = useMap()
  useEffect(() => {
    if (focus) map.flyToBounds(focus.bounds, { ...fitOptions(map), duration: 0.8 })
  }, [map, focus])
  return null
}

/**
 * Reports the visible extent after every pan/zoom. The listener is bound once: re-binding
 * on each render would leave a gap in which the load-time fit's moveend goes unheard.
 */
function ReportBounds({ onChange }: { onChange?: (b: ViewBounds) => void }) {
  const map = useMap()
  const onChangeRef = useRef(onChange)
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])
  useEffect(() => {
    function report() {
      const b = map.getBounds()
      onChangeRef.current?.({
        south: b.getSouth(),
        west: b.getWest(),
        north: b.getNorth(),
        east: b.getEast(),
      })
    }
    map.on('moveend', report)
    report()
    return () => {
      map.off('moveend', report)
    }
  }, [map])
  return null
}

function SmoothWheelZoom() {
  const map = useMap()
  useEffect(() => enableSmoothWheelZoom(map), [map])
  return null
}

function projectTooltip(p: Project): string {
  const when = rangeLabel(p.start_date, p.end_date, p.start_precision, p.end_precision)
  const parts = [
    `<strong>${esc(p.name || 'Unnamed project')}</strong>`,
    esc(
      [p.utility, p.type ?? 'type unknown', p.voltage_kv ? `${p.voltage_kv} kV` : null]
        .filter(Boolean)
        .join(' · '),
    ),
  ]
  if (when !== '—') parts.push(esc(when))
  if (p.approximate) parts.push('<em>Approximate location (county center)</em>')
  return parts.join('<br/>')
}

/**
 * One project dot. Memoised so hovering a pair repaints the two markers it touches instead of
 * re-rendering ~2,000, and never re-rendered by zooming: its `zoomStyle` lets the canvas size
 * it for the zoom as it draws. The tooltip is built on first open, not mounted per marker.
 */
const ProjectMarker = memo(function ProjectMarker({
  project: p,
  color,
  paired,
  highlighted,
  onSelect,
  onHover,
}: {
  project: Project
  color: string
  paired: boolean
  highlighted: boolean
  onSelect: (p: Project) => void
  onHover?: (p: Project | null) => void
}) {
  const ref = useRef<LeafletCircleMarker>(null)
  const zoom = useMap().getZoom()
  const state = { paired, selected: highlighted }
  const zoomStyle: ZoomStyle = (z) => markerStyle(p, color, state, z)
  const style = { ...markerStyle(p, color, state, zoom), zoomStyle }
  useEffect(() => {
    const m = ref.current
    if (!m) return
    m.bindTooltip(() => projectTooltip(p))
    return () => void m.unbindTooltip()
  }, [p])
  // Canvas paints in insertion order; lift the highlighted pair above its neighbours.
  useEffect(() => {
    if (highlighted) ref.current?.bringToFront()
  }, [highlighted])
  const handlers = useMemo(
    () => ({
      click: () => onSelect(p),
      mouseover: () => onHover?.(p),
      mouseout: () => onHover?.(null),
    }),
    [p, onSelect, onHover],
  )
  return (
    <CircleMarker
      ref={ref}
      center={[p.lat!, p.lng!]}
      radius={style.radius}
      pathOptions={style}
      eventHandlers={handlers}
    />
  )
})

const PAIR_INK = { light: { idle: '#3d4852', active: '#111' }, dark: { idle: '#c3ccd4', active: '#fff' } }

/** Ends this close (degrees, ~1 m) are one point: the projects touch or cross there. */
const SAME_POINT = 1e-5

/**
 * The connector between a pair's two projects, neutral so it never reads as a project colour.
 * It spans the gap the distance measures; projects that touch get a ring at the touch point.
 */
const PairLine = memo(function PairLine({
  pair,
  selected,
  hovered,
  scheme,
  onSelect,
}: {
  pair: CoordinationPair
  selected: boolean
  hovered: boolean
  scheme: 'light' | 'dark'
  onSelect?: (pair: CoordinationPair) => void
}) {
  const ref = useRef<LeafletPolyline | LeafletCircleMarker>(null)
  const [from, to] = pairEnds(pair)
  const touching = Math.abs(from[0] - to[0]) < SAME_POINT && Math.abs(from[1] - to[1]) < SAME_POINT
  const active = selected || hovered
  const zoom = useMap().getZoom()
  useEffect(() => {
    const l = ref.current
    if (!l) return
    const where = touching ? 'touching' : `${milesToKm(pair.miles).toFixed(1)} km apart`
    l.bindTooltip(
      () => esc(`${where} · ${bothBuildingLabel(pair)} (${durationLabel(pair.overlap_days)})`),
      { sticky: true },
    )
    return () => void l.unbindTooltip()
  }, [pair, touching])
  useEffect(() => {
    if (active) ref.current?.bringToFront()
  }, [active])
  const handlers = useMemo(() => (onSelect ? { click: () => onSelect(pair) } : {}), [pair, onSelect])
  const ink = selected ? PAIR_INK[scheme].active : PAIR_INK[scheme].idle
  if (touching) {
    // Radius goes in the path options too: restyling a circle falls back to its current,
    // zoom-sized radius otherwise.
    const ring: PathOptions & { radius: number; zoomStyle?: ZoomStyle } = {
      ...(active ? highlightSize(zoom) : { radius: 8, weight: 2 }),
      zoomStyle: active ? highlightSize : undefined,
      color: ink,
      opacity: active ? 0.95 : 0.5,
      fill: false,
    }
    return (
      <CircleMarker
        ref={ref as Ref<LeafletCircleMarker>}
        center={from}
        radius={ring.radius}
        pathOptions={ring}
        eventHandlers={handlers}
      />
    )
  }
  return (
    <Polyline
      ref={ref as Ref<LeafletPolyline>}
      positions={[from, to]}
      pathOptions={{
        color: ink,
        weight: active ? 4.5 : 1.8,
        opacity: active ? 0.95 : 0.5,
        dashArray: active ? undefined : '3 5',
      }}
      eventHandlers={handlers}
    />
  )
})

type MapLayer = 'grid' | 'counties' | 'labels'
const MAP_LAYERS: [MapLayer, string][] = [
  ['grid', 'Power grid'],
  ['counties', 'County lines'],
  ['labels', 'Place names'],
]

interface Props {
  projects: Project[]
  pairs: CoordinationPair[]
  selectedPair: CoordinationPair | null
  hoveredPair?: CoordinationPair | null
  /** Marker colour under the current "colour by" choice. */
  colorOf: (p: Project) => string
  colorBy: ColorBy
  onColorBy: (by: ColorBy) => void
  legend: LegendEntry[]
  scheme?: 'light' | 'dark'
  onSelectProject: (p: Project) => void
  onSelectPair?: (pair: CoordinationPair) => void
  onHoverProject?: (p: Project | null) => void
  onBoundsChange?: (b: ViewBounds) => void
  /** Fly here when it changes (search picks). */
  focus?: MapFocus | null
}

export function MapView({
  projects,
  pairs,
  selectedPair,
  hoveredPair = null,
  colorOf,
  colorBy,
  onColorBy,
  legend,
  scheme = 'light',
  onSelectProject,
  onSelectPair,
  onHoverProject,
  onBoundsChange,
  focus = null,
}: Props) {
  const [layers, setLayers] = useState<Record<MapLayer, boolean>>({
    grid: true,
    counties: true,
    labels: true,
  })
  const [map, setMap] = useState<LeafletMap | null>(null)
  const renderer = useMemo(() => new LiveZoomCanvas(), [])
  const wrap = useRef<HTMLDivElement>(null)

  // Leaflet only watches the window; the split layout resizes the map on its own
  // (panel width, filter bar wrapping), so redraw whenever the container changes size.
  useEffect(() => {
    if (!map || !wrap.current || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [map])

  const placed = useMemo(() => projects.filter((p) => p.lat != null && p.lng != null), [projects])
  const pairedIds = useMemo(
    () => new Set(pairs.flatMap((p) => [p.project_a.id, p.project_b.id])),
    [pairs],
  )
  const highlightedIds = new Set(
    [selectedPair, hoveredPair].flatMap((p) => (p ? [p.project_a.id, p.project_b.id] : [])),
  )

  const allBounds = useMemo<LatLngBoundsExpression | null>(() => {
    const pts = placed.map((p) => [p.lat!, p.lng!] as [number, number])
    return pts.length ? pts : null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed.length])

  // Keyed on coordinates, not the pair object, so a data refresh doesn't re-trigger the fly.
  const a = selectedPair?.project_a
  const b = selectedPair?.project_b
  const routeKey = JSON.stringify([a?.route ?? null, b?.route ?? null])
  const pairBounds = useMemo<LatLngBoundsExpression | null>(() => {
    if (a?.lat == null || a.lng == null || b?.lat == null || b.lng == null) return null
    return [
      [a.lat, a.lng],
      [b.lat, b.lng],
      ...(a.route ?? []),
      ...(b.route ?? []),
    ]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.lat, a?.lng, b?.lat, b?.lng, routeKey])

  // Unpaired first so paired markers paint on top; the open/hovered pair lifts itself.
  const ordered = useMemo(
    () => [...placed].sort((x, y) => +pairedIds.has(x.id) - +pairedIds.has(y.id)),
    [placed, pairedIds],
  )
  const placedPairs = useMemo(
    () => pairs.filter((p) => p.project_a.lat != null && p.project_b.lat != null),
    [pairs],
  )

  // On a small map (stacked tablet layout, squeezed split) the open colour card hides the
  // Southeast, where most projects are: start it collapsed there. Runs once, before the
  // first fit and paint; after that the planner's own toggles stand.
  const colorCard = useRef<HTMLDetailsElement>(null)
  useLayoutEffect(() => {
    const el = wrap.current
    if (el && colorCard.current && !legendStartsOpen(el.clientWidth, el.clientHeight)) {
      colorCard.current.open = false
    }
  }, [])

  return (
    <div className="map-wrap" ref={wrap}>
      <MapContainer
        ref={setMap}
        center={[39.8, -77.1]}
        zoom={9}
        // Far enough out to frame projects from Hawaii to Maine; the power grid draws down to
        // this floor too (POWER_MIN_ZOOM).
        minZoom={3}
        zoomSnap={0}
        scrollWheelZoom={false}
        // Thousands of markers and connectors: one canvas instead of an SVG node each.
        renderer={renderer}
        className="map"
      >
        <SmoothWheelZoom />
        <ScaleControl position="bottomleft" imperial={false} metric />
        <BaseMap counties={layers.counties} labels={layers.labels} />
        {layers.grid ? <PowerGridLayer /> : null}
        <ViewController allBounds={allBounds} pairBounds={pairBounds} />
        <FocusController focus={focus} />
        <ReportBounds onChange={onBoundsChange} />
        {/* Planned lines: a straight segment between the endpoint substations. */}
        {ordered
          .filter((p) => p.route && p.route.length >= 2)
          .map((p) => {
            const highlighted = highlightedIds.has(p.id)
            const paired = pairedIds.has(p.id)
            return (
              <Polyline
                key={`route-${p.id}`}
                positions={p.route!}
                pathOptions={{
                  color: colorOf(p),
                  weight: highlighted ? 7 : paired ? 5 : 2.5,
                  opacity: highlighted ? 1 : paired ? 0.85 : 0.5,
                  lineCap: 'round',
                }}
                eventHandlers={{
                  click: () => onSelectProject(p),
                  mouseover: () => onHoverProject?.(p),
                  mouseout: () => onHoverProject?.(null),
                }}
              >
                <Tooltip sticky>
                  <strong>{p.name || 'Unnamed project'}</strong>
                  <br />
                  {p.utility} · planned line (straight between endpoints)
                </Tooltip>
              </Polyline>
            )
          })}
        {placedPairs.map((pair) => (
          <PairLine
            key={pair.id}
            pair={pair}
            selected={selectedPair?.id === pair.id}
            hovered={hoveredPair?.id === pair.id}
            scheme={scheme}
            onSelect={onSelectPair}
          />
        ))}
        {ordered.map((p) => (
          <ProjectMarker
            key={p.id}
            project={p}
            color={colorOf(p)}
            paired={pairedIds.has(p.id)}
            highlighted={highlightedIds.has(p.id)}
            onSelect={onSelectProject}
            onHover={onHoverProject}
          />
        ))}
      </MapContainer>
      <div className="map-notes">
        {projects.length > placed.length ? (
          <p className="map-note">
            {projects.length - placed.length} project(s) have no location yet — see Review.
          </p>
        ) : null}
      </div>
      <div className="map-tools">
        {map && allBounds ? (
          <button
            type="button"
            className="map-fit"
            onClick={() => map.flyToBounds(allBounds, { ...fitOptions(map), duration: 0.8 })}
          >
            Fit all
          </button>
        ) : null}
        <details className="legend-card color-card" open ref={colorCard}>
          <summary>
            Color by {COLOR_BY_OPTIONS.find(([k]) => k === colorBy)?.[1].toLowerCase()}
          </summary>
          <div className="color-by" role="group" aria-label="Color projects by">
            {COLOR_BY_OPTIONS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={colorBy === key ? 'active' : ''}
                aria-pressed={colorBy === key}
                onClick={() => onColorBy(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <ul className="color-legend" aria-label="Project colors">
            {legend.map((r) => (
              <li key={r.label}>
                <span className="swatch" style={{ background: r.color }} />
                <span className="color-legend-label" title={r.label}>
                  {r.label}
                </span>
                <span className="color-legend-count">{r.count.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </details>
        <details className="legend-card">
          <summary>Layers &amp; legend</summary>
          <div className="map-legend layer-toggles" aria-label="Map layers">
            {MAP_LAYERS.map(([key, label]) => (
              <label key={key} className="legend-item">
                <input
                  type="checkbox"
                  checked={layers[key]}
                  onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))}
                />
                {label}
              </label>
            ))}
          </div>
          <div className="map-legend" aria-label="Marker legend">
            <span className="legend-item">
              <span className="swatch swatch-paired" /> in a potential coordination opportunity
            </span>
            <span className="legend-item">
              <span className="swatch swatch-approx" /> approximate location
            </span>
            <span className="legend-item">
              <span className="swatch swatch-line swatch-pair-line" /> pair connector (closest
              points; a ring where they touch)
            </span>
            <span className="legend-item">
              <span className="swatch swatch-line" style={{ background: 'var(--ink-2)' }} />{' '}
              planned line (straight between endpoints)
            </span>
          </div>
          {layers.grid ? (
            <div className="map-legend grid-legend" aria-label="Power grid legend">
              <span>Power grid (kV):</span>
              {[...VOLTAGE_SCALE].reverse().map(([kv, c]) => (
                <span key={kv} className="legend-item">
                  <span className="swatch swatch-line" style={{ background: c }} />
                  {kv}+
                </span>
              ))}
              <span className="legend-item">
                <span className="swatch swatch-line" style={{ background: LOW_VOLTAGE_COLOR }} />
                lower / unknown
              </span>
              {layers.grid ? (
                <>
                  <span className="legend-item">
                    <span className="swatch swatch-substation" /> substation
                  </span>
                  <span className="legend-item">
                    <span className="swatch swatch-plant" /> power plant
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
        </details>
      </div>
    </div>
  )
}
