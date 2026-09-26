import 'leaflet/dist/leaflet.css'

import type { GeoJsonObject } from 'geojson'
import type { LatLngBoundsExpression, LatLngExpression, Layer, Map as LeafletMap } from 'leaflet'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  Polyline,
  ScaleControl,
  Tooltip,
  useMap,
} from 'react-leaflet'

import { milesToKm } from '../lib/distanceBands'
import { timingLabel } from '../lib/format'
import { lineBounds, lineOwners, lineStyle, lineTooltip, UNKNOWN_OWNER } from '../lib/lines'
import { markerStyle } from '../lib/mapStyle'
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

function SmoothWheelZoom() {
  const map = useMap()
  useEffect(() => enableSmoothWheelZoom(map), [map])
  return null
}

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
  colors: Record<string, string>
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
  colors,
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
  const wrap = useRef<HTMLDivElement>(null)

  // Leaflet only watches the window; the split layout resizes the map on its own
  // (panel width, filter bar wrapping), so redraw whenever the container changes size.
  useEffect(() => {
    if (!map || !wrap.current || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [map])

  const owners = useMemo(() => (lines ? lineOwners(lines) : []), [lines])
  const projectUtilities = useMemo(
    () => [...new Set(projects.map((p) => p.utility))].sort((a, b) => a.localeCompare(b)),
    [projects],
  )
  const placed = projects.filter((p) => p.lat != null && p.lng != null)
  const pairedIds = useMemo(
    () => new Set(pairs.flatMap((p) => [p.project_a.id, p.project_b.id])),
    [pairs],
  )
  const selectedIds = new Set(
    selectedPair ? [selectedPair.project_a.id, selectedPair.project_b.id] : [],
  )
  const hoveredIds = new Set(
    hoveredPair ? [hoveredPair.project_a.id, hoveredPair.project_b.id] : [],
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

  // Draw unselected, then paired, then selected so highlighted markers sit on top.
  const ordered = [...placed].sort((a, b) => rank(a) - rank(b))
  function rank(p: Project) {
    return selectedIds.has(p.id) ? 3 : hoveredIds.has(p.id) ? 2 : pairedIds.has(p.id) ? 1 : 0
  }

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
        className="map"
      >
        <SmoothWheelZoom />
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
              style={(f) => lineStyle(f as unknown as LineFeature, colors)}
              onEachFeature={(f, layer: Layer) =>
                layer.bindTooltip(lineTooltip(f as unknown as LineFeature), { sticky: true })
              }
            />
          ) : null}
        </Pane>
        {/* Planned lines: a straight segment between the endpoint substations. */}
        {ordered
          .filter((p) => p.route && p.route.length >= 2)
          .map((p) => {
            const highlighted = selectedIds.has(p.id) || hoveredIds.has(p.id)
            return (
              <Polyline
                key={`route-${p.id}`}
                positions={p.route!}
                pathOptions={{
                  color: colors[p.utility] ?? '#555',
                  weight: highlighted ? 6 : pairedIds.has(p.id) ? 4 : 2.5,
                  opacity: highlighted ? 1 : pairedIds.has(p.id) ? 0.85 : 0.5,
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
        {pairs.map((pair) => {
          const { project_a: a, project_b: b } = pair
          if (a.lat == null || b.lat == null) return null
          const selected = selectedPair?.id === pair.id
          const hovered = hoveredPair?.id === pair.id
          return (
            <Polyline
              key={pair.id}
              positions={[
                [a.lat, a.lng!],
                [b.lat, b.lng!],
              ]}
              pathOptions={{
                color: selected ? '#111' : '#f08c00',
                weight: selected || hovered ? 3.5 : 1.5,
                opacity: selected || hovered ? 0.95 : 0.45,
                dashArray: selected || hovered ? undefined : '3 5',
              }}
              eventHandlers={onSelectPair ? { click: () => onSelectPair(pair) } : undefined}
            >
              <Tooltip sticky>
                {milesToKm(pair.miles).toFixed(1)} km · {timingLabel(pair)}
              </Tooltip>
            </Polyline>
          )
        })}
        {ordered.map((p) => {
          const style = markerStyle(p, colors[p.utility] ?? '#555', {
            paired: pairedIds.has(p.id),
            selected: selectedIds.has(p.id) || hoveredIds.has(p.id),
          })
          return (
            <CircleMarker
              key={p.id}
              center={[p.lat!, p.lng!]}
              radius={style.radius}
              pathOptions={style}
              eventHandlers={{
                click: () => onSelectProject(p),
                mouseover: () => onHoverProject?.(p),
                mouseout: () => onHoverProject?.(null),
              }}
            >
              <Tooltip>
                <strong>{p.name || 'Unnamed project'}</strong>
                <br />
                {p.utility} · {p.type ?? 'type unknown'}
                {p.voltage_kv ? ` · ${p.voltage_kv} kV` : ''}
                {p.approximate ? (
                  <>
                    <br />
                    <em>Approximate location (county center)</em>
                  </>
                ) : null}
              </Tooltip>
            </CircleMarker>
          )
        })}
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
          <div className="map-legend utility-legend" aria-label="Map legend">
            {projectUtilities.map((u) => (
              <span key={u} className="legend-item">
                <span className="swatch" style={{ background: colors[u] ?? '#555' }} />
                {u}
              </span>
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
              <span className="swatch swatch-line" style={{ background: 'var(--ink-2)' }} />{' '}
              planned line (straight between endpoints)
            </span>
          </div>
          {layers.grid ? (
            <div className="map-legend grid-legend" aria-label="Power grid legend">
              <span>Grid lines (kV):</span>
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
              <span className="legend-item">
                <span className="swatch swatch-substation" /> substation
              </span>
              <span className="legend-item">
                <span className="swatch swatch-plant" /> power plant
              </span>
            </div>
          ) : null}
          {lines && owners.length ? (
            <div className="map-legend lines-legend" aria-label="Existing transmission lines">
              <label className="legend-item">
                <input
                  type="checkbox"
                  checked={showLines}
                  onChange={(e) => setShowLines(e.target.checked)}
                />
                Existing lines (HIFLD)
              </label>
              {showLines
                ? owners.map(({ owner, count }) => (
                    <span key={owner ?? UNKNOWN_OWNER} className="legend-item">
                      <span
                        className="swatch swatch-line"
                        style={{ background: owner ? (colors[owner] ?? '#555') : undefined }}
                      />
                      {owner ?? UNKNOWN_OWNER} ({count})
                    </span>
                  ))
                : null}
            </div>
          ) : null}
        </details>
      </div>
    </div>
  )
}
