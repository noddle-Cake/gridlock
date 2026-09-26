import 'leaflet/dist/leaflet.css'

import type { GeoJsonObject } from 'geojson'
import type {
  CircleMarker as LeafletCircleMarker,
  LatLngBoundsExpression,
  LatLngExpression,
  Layer,
  Map as LeafletMap,
  Polyline as LeafletPolyline,
} from 'leaflet'
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  Polyline,
  ScaleControl,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet'

import { milesToKm } from '../lib/distanceBands'
import { escapeHtml as esc, rangeLabel, timingLabel } from '../lib/format'
import { lineBounds, lineStyle, lineTooltip } from '../lib/lines'
import {
  COLOR_BY_OPTIONS,
  type ColorBy,
  type LegendEntry,
  PAIR_LINE_MIN_ZOOM,
  markerScale,
  markerStyle,
} from '../lib/mapStyle'
import type { ViewBounds } from '../lib/pairs'
import { LOW_VOLTAGE_COLOR, VOLTAGE_SCALE } from '../lib/powerGrid'
import { enableSmoothWheelZoom } from '../lib/smoothWheelZoom'
import type { CoordinationPair, LineCollection, LineFeature, Project } from '../types'
import { BaseMap } from './BaseMap'
import { PowerGridLayer } from './PowerGridLayer'

const FIT = { padding: [40, 40] as [number, number], maxZoom: 11 }

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
    const glide = { ...FIT, duration: 0.8 }

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
    else map.fitBounds(allBounds, { ...FIT, animate: false })
    fitted.current = true
  }, [map, allBounds, pairBounds])
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

function ZoomWatcher({ onZoom }: { onZoom: (z: number) => void }) {
  const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) })
  useEffect(() => onZoom(map.getZoom()), [map, onZoom])
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
 * re-rendering ~2,000. The tooltip is built on first open rather than mounted per marker.
 */
const ProjectMarker = memo(function ProjectMarker({
  project: p,
  color,
  paired,
  highlighted,
  scale,
  onSelect,
  onHover,
}: {
  project: Project
  color: string
  paired: boolean
  highlighted: boolean
  scale: number
  onSelect: (p: Project) => void
  onHover?: (p: Project | null) => void
}) {
  const ref = useRef<LeafletCircleMarker>(null)
  const style = markerStyle(p, color, { paired, selected: highlighted }, scale)
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

/** The connector between a pair's two projects, neutral so it never reads as a project colour. */
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
  const ref = useRef<LeafletPolyline>(null)
  const { project_a: a, project_b: b } = pair
  const active = selected || hovered
  useEffect(() => {
    const l = ref.current
    if (!l) return
    l.bindTooltip(() => esc(`${milesToKm(pair.miles).toFixed(1)} km · ${timingLabel(pair)}`), {
      sticky: true,
    })
    return () => void l.unbindTooltip()
  }, [pair])
  useEffect(() => {
    if (active) ref.current?.bringToFront()
  }, [active])
  const handlers = useMemo(() => (onSelect ? { click: () => onSelect(pair) } : {}), [pair, onSelect])
  return (
    <Polyline
      ref={ref}
      positions={[
        [a.lat!, a.lng!],
        [b.lat!, b.lng!],
      ]}
      pathOptions={{
        color: selected ? PAIR_INK[scheme].active : PAIR_INK[scheme].idle,
        weight: active ? 3.5 : 1.2,
        opacity: active ? 0.95 : 0.35,
        dashArray: active ? undefined : '3 5',
      }}
      eventHandlers={handlers}
    />
  )
})

type MapLayer = 'grid' | 'highways' | 'counties' | 'labels'
const MAP_LAYERS: [MapLayer, string][] = [
  ['grid', 'Power grid'],
  ['highways', 'Highways'],
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
  lines?: LineCollection | null
  linesFailed?: boolean
  onSelectProject: (p: Project) => void
  onSelectPair?: (pair: CoordinationPair) => void
  onHoverProject?: (p: Project | null) => void
  onBoundsChange?: (b: ViewBounds) => void
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
  lines = null,
  linesFailed = false,
  onSelectProject,
  onSelectPair,
  onHoverProject,
  onBoundsChange,
}: Props) {
  const [showLines, setShowLines] = useState(true)
  const [layers, setLayers] = useState<Record<MapLayer, boolean>>({
    grid: true,
    highways: true,
    counties: true,
    labels: true,
  })
  const [map, setMap] = useState<LeafletMap | null>(null)
  const [zoom, setZoom] = useState(9)
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
    // With no placed projects yet, frame the reference lines instead.
    return pts.length ? pts : lines ? lineBounds(lines) : null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed.length, lines])

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

  return (
    <div className="map-wrap" ref={wrap}>
      <MapContainer
        ref={setMap}
        center={[39.8, -77.1]}
        zoom={9}
        // Without an explicit floor Leaflet borrows the grid tiles' minZoom (5), which is
        // too close to frame projects from Hawaii to Maine. The grid layer just switches off
        // below its own minimum.
        minZoom={3}
        zoomSnap={0}
        scrollWheelZoom={false}
        // Thousands of markers and connectors: one canvas per pane instead of an SVG node each.
        preferCanvas
        className="map"
      >
        <SmoothWheelZoom />
        <ZoomWatcher onZoom={setZoom} />
        <ScaleControl position="bottomleft" imperial={false} metric />
        <BaseMap highways={layers.highways} counties={layers.counties} labels={layers.labels} />
        {layers.grid ? <PowerGridLayer /> : null}
        <ViewController allBounds={allBounds} pairBounds={pairBounds} />
        <ReportBounds onChange={onBoundsChange} />
        {/* Existing lines sit in their own pane under the project markers. */}
        <Pane name="reference-lines" style={{ zIndex: 350 }}>
          {lines && showLines ? (
            <GeoJSON
              key={lines.features.length}
              data={lines as unknown as GeoJsonObject}
              style={(f) => lineStyle(f as unknown as LineFeature)}
              onEachFeature={(f, layer: Layer) =>
                layer.bindTooltip(() => lineTooltip(f as unknown as LineFeature), { sticky: true })
              }
            />
          ) : null}
        </Pane>
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
                  weight: highlighted ? 6 : paired ? 4 : 2.5,
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
        {placedPairs
          .filter(
            (pair) =>
              zoom >= PAIR_LINE_MIN_ZOOM ||
              pair.id === selectedPair?.id ||
              pair.id === hoveredPair?.id,
          )
          .map((pair) => (
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
            scale={markerScale(zoom)}
            onSelect={onSelectProject}
            onHover={onHoverProject}
          />
        ))}
      </MapContainer>
      <div className="map-notes">
        {linesFailed ? <p className="map-note">Existing transmission lines could not be loaded.</p> : null}
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
            onClick={() => map.flyToBounds(allBounds, { ...FIT, duration: 0.8 })}
          >
            Fit all
          </button>
        ) : null}
        <details className="legend-card color-card" open>
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
            {lines ? (
              <label className="legend-item">
                <input
                  type="checkbox"
                  checked={showLines}
                  onChange={(e) => setShowLines(e.target.checked)}
                />
                Existing lines (HIFLD)
              </label>
            ) : null}
          </div>
          <div className="map-legend" aria-label="Marker legend">
            <span className="legend-item">
              <span className="swatch swatch-paired" /> in a potential coordination opportunity
            </span>
            <span className="legend-item">
              <span className="swatch swatch-approx" /> approximate location
            </span>
            <span className="legend-item">
              <span className="swatch swatch-line swatch-pair-line" /> pair connector
            </span>
            <span className="legend-item">
              <span className="swatch swatch-line" style={{ background: 'var(--ink-2)' }} />{' '}
              planned line (straight between endpoints)
            </span>
          </div>
          {layers.grid || (lines && showLines) ? (
            <div className="map-legend grid-legend" aria-label="Power grid legend">
              <span>Grid &amp; existing lines (kV):</span>
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
