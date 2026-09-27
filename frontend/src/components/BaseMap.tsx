import type { FeatureCollection, GeoJsonObject } from 'geojson'
import L from 'leaflet'
import { useEffect, useMemo, useState } from 'react'
import { useMap, useMapEvents } from 'react-leaflet'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'

import {
  BASEMAP_ATTRIBUTION,
  BASEMAP_URL,
  COUNTY_LABEL_MIN_ZOOM,
  COUNTY_MIN_ZOOM,
  MAJOR_CITY,
  type LabelCandidate,
  type LabelData,
  type NamedPoint,
  STATE_LABEL_MAX_ZOOM,
  chunkLines,
  countyLines,
  layoutLabels,
  minPlacePopulation,
  nationalOutlines,
  placeTier,
  stateBorders,
  textWidth,
} from '../lib/basemap'
import { ScaledRedrawCanvas } from '../lib/liveCanvas'
import { useColorScheme } from '../lib/useColorScheme'

// Outlines sit under the power-grid tiles (tilePane is 200); names sit above the grid
// but under project markers (overlayPane, 400).
const SHAPES_PANE = 'basemap-shapes'
const LABELS_PANE = 'basemap-labels'

// Each file is fetched at most once per page load, the first time it is needed.
const cache = new Map<string, Promise<unknown>>()
function useBasemapFile<T>(file: string, needed: boolean): T | null {
  const [data, setData] = useState<T | null>(null)
  useEffect(() => {
    if (!needed || data) return
    let live = true
    if (!cache.has(file)) {
      const req = fetch(BASEMAP_URL + file).then((r) => {
        if (!r.ok) throw new Error(`${file}: ${r.status}`)
        return r.json()
      })
      // A failed download may be retried on the next attempt instead of being cached.
      req.catch(() => cache.delete(file))
      cache.set(file, req)
    }
    cache
      .get(file)!
      .then((d) => live && setData(d as T))
      .catch(() => {}) // the base map is context only; the map still works without it
    return () => {
      live = false
    }
  }, [file, needed, data])
  return data
}

/** Canvas colours come from the --map-* CSS tokens so light and dark themes stay in one place. */
function palette() {
  const s = getComputedStyle(document.documentElement)
  const v = (name: string) => s.getPropertyValue(name).trim()
  return {
    land: v('--map-land'),
    foreign: v('--map-land-foreign'),
    water: v('--map-water'),
    outline: v('--map-outline'),
    border: v('--map-border'),
    county: v('--map-county'),
  }
}

const shapes = (
  data: GeoJsonObject,
  renderer: L.Renderer,
  // minZoom: see ScaledRedrawCanvas.
  style: L.StyleFunction | (L.PathOptions & { minZoom?: number }),
) => L.geoJSON(data, { renderer, interactive: false, style } as L.GeoJSONOptions)

const topoFeatures = (topo: Topology, name: string) =>
  feature(topo, topo.objects[name] as GeometryCollection) as FeatureCollection

interface Props {
  counties: boolean
  labels: boolean
}

/** Reference base map: land and water, state/national/county lines and place names. */
export function BaseMap({ counties, labels }: Props) {
  const map = useMap()
  const scheme = useColorScheme()
  const [zoom, setZoom] = useState(() => map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })

  const showCounties = counties && zoom >= COUNTY_MIN_ZOOM
  const land = useBasemapFile<Topology>('land.json', true)
  const labelData = useBasemapFile<LabelData>('labels.json', labels)
  const countyTopo = useBasemapFile<Topology>('counties.json', showCounties)
  const countyNames = useBasemapFile<NamedPoint[]>(
    'county-labels.json',
    counties && labels && zoom >= COUNTY_LABEL_MIN_ZOOM,
  )

  const renderer = useMemo(() => {
    for (const [name, z] of [
      [SHAPES_PANE, 150],
      [LABELS_PANE, 390],
    ] as const) {
      if (!map.getPane(name)) {
        const pane = map.createPane(name)
        pane.style.zIndex = String(z)
        pane.style.pointerEvents = 'none'
      }
    }
    // Redrawn every frame of a zoom so borders keep their width instead of stretching.
    return new ScaledRedrawCanvas({ pane: SHAPES_PANE, padding: 0.3 })
  }, [map])

  useEffect(() => {
    map.attributionControl?.addAttribution(BASEMAP_ATTRIBUTION)
    return () => void map.attributionControl?.removeAttribution(BASEMAP_ATTRIBUTION)
  }, [map])

  useEffect(() => {
    if (!land) return
    const c = palette()
    const fill = (color: string) => ({
      stroke: false,
      fill: true,
      fillColor: color,
      fillOpacity: 1,
    })
    const group = L.layerGroup([
      shapes(topoFeatures(land, 'countries'), renderer, fill(c.foreign)),
      shapes(topoFeatures(land, 'states'), renderer, fill(c.land)),
      shapes(topoFeatures(land, 'lakes'), renderer, fill(c.water)),
      ...nationalOutlines(land).map((m) =>
        shapes(chunkLines(m), renderer, { color: c.outline, weight: 1 }),
      ),
      shapes(chunkLines(stateBorders(land)), renderer, {
        color: c.border,
        weight: 1.4,
        dashArray: '6 3 1.5 3',
      }),
    ]).addTo(map)
    return () => void group.remove()
  }, [map, renderer, land, scheme])

  useEffect(() => {
    if (!countyTopo || !showCounties) return
    const layer = shapes(chunkLines(countyLines(countyTopo)), renderer, {
      // Dropped mid-zoom below the zoom they show at (lib/liveCanvas.ts), not just at zoomend.
      minZoom: COUNTY_MIN_ZOOM,
      color: palette().county,
      weight: 0.8,
      dashArray: '2 3',
    }).addTo(map)
    return () => void layer.remove()
  }, [map, renderer, countyTopo, showCounties, scheme])

  useEffect(() => {
    if (!labels) return
    const layer = L.layerGroup().addTo(map)
    const markers = new Map<string, L.Marker>()

    function place() {
      const z = map.getZoom()
      const view = map.getBounds().pad(0.15)
      const at = (lat: number, lng: number) => map.latLngToContainerPoint([lat, lng])
      const html = new Map<string, { lat: number; lng: number; cls: string; body: string }>()
      const cands: LabelCandidate[] = []
      const add = (
        key: string,
        lat: number,
        lng: number,
        text: string,
        cls: string,
        box: LabelCandidate['box'],
        body: string,
        repeatGap?: number,
      ) => {
        if (!view.contains([lat, lng])) return
        const p = at(lat, lng)
        cands.push({ key, x: p.x, y: p.y, box, text, repeatGap })
        html.set(key, { lat, lng, cls, body })
      }
      const centred = (w: number, h: number) => ({ left: -w / 2, top: -h / 2, width: w, height: h })
      const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`)

      // Towns in [from, below) population, biggest first (the file is sorted that way).
      const addPlaces = (from: number, below: number) => {
        if (!labelData) return
        let n = 0
        for (const [name, lat, lng, pop] of labelData.places) {
          if (pop < from || n > 4000) break
          if (pop >= below || !view.contains([lat, lng])) continue
          n++
          const tier = placeTier(pop)
          const font = tier === 'city' ? 13 : tier === 'town' ? 12 : 11
          const w = textWidth(name, font) + 8
          add(
            `p:${name}:${lat}:${lng}`,
            lat,
            lng,
            name,
            `map-label-place map-label-${tier}`,
            { left: -3, top: -font / 2 - 1, width: w, height: font + 2 },
            `<i></i><span>${esc(name)}</span>`,
          )
        }
      }
      // Priority: big cities, then state names, then smaller towns, counties.
      const min = minPlacePopulation(z)
      addPlaces(Math.max(min, MAJOR_CITY), Infinity)
      if (labelData && z >= 4 && z <= STATE_LABEL_MAX_ZOOM) {
        for (const [name, lat, lng] of labelData.states) {
          // Washington's city label already names DC, and the district is too small for both.
          if (name === 'District of Columbia') continue
          const w = textWidth(name, 12) + name.length * 1.5
          add(
            `s:${name}`,
            lat,
            lng,
            name,
            'map-label-state',
            centred(w, 14),
            `<span>${esc(name)}</span>`,
          )
        }
      }
      addPlaces(min, MAJOR_CITY)
      if (countyNames && counties && z >= COUNTY_LABEL_MIN_ZOOM) {
        for (const [name, lat, lng] of countyNames) {
          const w = textWidth(name, 11)
          add(
            `c:${name}:${lat}`,
            lat,
            lng,
            name,
            'map-label-county',
            centred(w, 13),
            `<span>${esc(name)}</span>`,
          )
        }
      }

      const keep = layoutLabels(cands)
      for (const [key, m] of markers) {
        if (!keep.has(key)) {
          layer.removeLayer(m)
          markers.delete(key)
        }
      }
      for (const key of keep) {
        if (markers.has(key)) continue
        const { lat, lng, cls, body } = html.get(key)!
        const icon = L.divIcon({ className: `map-label ${cls}`, html: body, iconSize: [0, 0] })
        const m = L.marker([lat, lng], {
          icon,
          interactive: false,
          keyboard: false,
          pane: LABELS_PANE,
        })
        markers.set(key, m.addTo(layer))
      }
    }

    place()
    map.on('moveend zoomend', place)
    return () => {
      map.off('moveend zoomend', place)
      layer.remove()
    }
  }, [map, labels, labelData, countyNames, counties])

  return null
}
