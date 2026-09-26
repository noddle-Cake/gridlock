// Builds the reference base map shipped in public/basemap/ from public-domain sources:
//   US Census Bureau cartographic boundaries, TIGER primary roads, place gazetteer and
//   population estimates; Natural Earth land for neighbouring countries and large lakes.
// Run with `npm run build:basemap` (needs network); the outputs are committed, so the app and CI
// never fetch these sources themselves. Downloads are cached in node_modules/.cache/basemap.

import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { unzipSync } from 'fflate'
import polylabel from 'polylabel'
import shapefile from 'shapefile'
import { quantize } from 'topojson-client'
import { topology } from 'topojson-server'
import { presimplify, simplify } from 'topojson-simplify'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(ROOT, 'public', 'basemap')
const CACHE = join(ROOT, 'node_modules', '.cache', 'basemap')

const CENSUS = 'https://www2.census.gov/geo'
const NE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson'
const SOURCES = {
  states: `${CENSUS}/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip`,
  counties: `${CENSUS}/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip`,
  roads: `${CENSUS}/tiger/TIGER2023/PRIMARYROADS/tl_2023_us_primaryroads.zip`,
  gazetteer: `${CENSUS}/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip`,
  population:
    'https://www2.census.gov/programs-surveys/popest/datasets/2020-2023/cities/totals/sub-est2023.csv',
  countries: `${NE}/ne_50m_admin_0_countries.geojson`,
  lakes: `${NE}/ne_50m_lakes.geojson`,
}

/** North America and the Caribbean (west, south, east, north). */
const NA_BBOX = [-170, 5, -50, 72]
/** Neighbouring countries only need drawing near the US: skip the Arctic and South America. */
const NEIGHBOUR_BBOX = [-140, 7, -52, 60]
/**
 * Drop vertices whose Visvalingam triangle is under this many deg²: about a pixel of detail
 * at zoom 10 (one pixel there is ~0.0014°, so ½·px² ≈ 1e-6).
 */
const MIN_AREA = 5e-7
/** Grid for stored coordinates: 2e5 steps across the US extent ≈ 50 m. */
const QUANTIZE = 2e5

async function download(name) {
  const url = SOURCES[name]
  const file = join(CACHE, url.split('/').pop())
  if (!(await stat(file).catch(() => null))) {
    console.log(`downloading ${url}`)
    const res = await fetch(url, { headers: { 'User-Agent': 'gridmerge-basemap-build' } })
    if (!res.ok) throw new Error(`${url}: ${res.status}`)
    await mkdir(CACHE, { recursive: true })
    await writeFile(file, Buffer.from(await res.arrayBuffer()))
  }
  return readFile(file)
}

async function readShapefile(name) {
  const files = unzipSync(new Uint8Array(await download(name)))
  const pick = (ext) => Object.entries(files).find(([f]) => f.endsWith(ext))[1]
  return shapefile.read(pick('.shp'), pick('.dbf'))
}

const round = (n, d) => Math.round(n * 10 ** d) / 10 ** d

/** Polygon parts as a list, whatever the geometry type. */
const polygons = (g) => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates)

/**
 * Keep only the polygon parts that touch `bbox`. Also drops Alaska's islands west of the
 * antimeridian, which would otherwise stretch the quantization grid round the whole globe.
 */
function clip(fc, [w, s, e, n]) {
  const inside = (poly) => poly[0].some(([x, y]) => x >= w && x <= e && y >= s && y <= n)
  const features = []
  for (const f of fc.features) {
    const kept = polygons(f.geometry).filter(inside)
    if (kept.length) features.push({ ...f, geometry: { type: 'MultiPolygon', coordinates: kept } })
  }
  return { type: 'FeatureCollection', features }
}

/** simplify() returns absolute float coordinates, so re-quantize afterwards. */
function build(objects, minArea = MIN_AREA) {
  return quantize(simplify(presimplify(topology(objects, 1e6)), minArea), QUANTIZE)
}

function slim(fc, props) {
  return {
    type: 'FeatureCollection',
    features: fc.features.map((f) => ({
      type: 'Feature',
      properties: props(f.properties),
      geometry: f.geometry,
    })),
  }
}

/** Pole of inaccessibility of the largest part: a label point that is always inside. */
function labelPoint(geometry) {
  const area = (ring) =>
    Math.abs(
      ring.reduce((sum, [x1, y1], i) => {
        const [x2, y2] = ring[(i + 1) % ring.length]
        return sum + x1 * y2 - x2 * y1
      }, 0),
    )
  const largest = polygons(geometry).reduce((a, b) => (area(b[0]) > area(a[0]) ? b : a))
  const [lng, lat] = polylabel(largest, 0.001)
  return [round(lat, 3), round(lng, 3)]
}

/** Land and water: US states, neighbouring countries, large lakes. Loaded up front. */
async function land() {
  const states = clip(await readShapefile('states'), NA_BBOX)
  const countries = JSON.parse(await download('countries'))
  countries.features = countries.features.filter((f) => f.properties.ADM0_A3 !== 'USA')
  const lakes = JSON.parse(await download('lakes'))
  // Only lakes big enough to orient by (Great Lakes, Okeechobee, Lake of the Woods...).
  lakes.features = lakes.features.filter((f) => f.properties.scalerank <= 4)
  const topo = build({
    states: slim(states, (p) => ({ id: p.STUSPS })),
    countries: slim(clip(countries, NEIGHBOUR_BBOX), (p) => ({ id: p.ADM0_A3 })),
    lakes: slim(clip(lakes, NA_BBOX), () => ({})),
  })
  const labels = states.features.map((f) => [f.properties.NAME, ...labelPoint(f.geometry)])
  return { topo, labels }
}

/** County outlines, tagged with their state so the client can skip lines that are state lines. */
async function counties() {
  const fc = clip(await readShapefile('counties'), NA_BBOX)
  // County lines are faint context that only shows from zoom 8, so allow a coarser outline.
  const topo = build({ counties: slim(fc, (p) => ({ st: p.STATEFP })) }, MIN_AREA * 6)
  const labels = fc.features.map((f) => [f.properties.NAMELSAD, ...labelPoint(f.geometry)])
  return { topo, labels }
}

/** "I- 95" → "I-95", "US Hwy 1" → "US 1"; other primary roads get no label. */
function routeLabel(name) {
  const i = /^I-\s*(\d+[A-Z]?)\b/.exec(name ?? '')
  if (i) return `I-${i[1]}`
  const us = /^US Hwy\s*(\d+[A-Z]?)\b/.exec(name ?? '')
  return us ? `US ${us[1]}` : ''
}

/** Interstates and US routes, one feature per route so each can carry a label. */
async function highways() {
  const roads = await readShapefile('roads')
  const byRef = new Map()
  for (const f of roads.features) {
    const ref = routeLabel(f.properties.FULLNAME)
    const parts =
      f.geometry.type === 'LineString' ? [f.geometry.coordinates] : f.geometry.coordinates
    const kept = parts.filter((c) => c.every(([x]) => x < 0))
    if (!byRef.has(ref)) byRef.set(ref, [])
    byRef.get(ref).push(...kept)
  }
  const fc = {
    type: 'FeatureCollection',
    features: [...byRef].map(([ref, coordinates]) => ({
      type: 'Feature',
      properties: { ref },
      geometry: { type: 'MultiLineString', coordinates },
    })),
  }
  // Road centrelines are dense (a vertex every few metres); thin them harder than boundaries.
  return build({ roads: fc }, MIN_AREA * 6)
}

/** Towns and cities: [name, lat, lng, population]; biggest first. */
async function places() {
  const pop = new Map()
  for (const row of (await download('population')).toString('latin1').split('\n').slice(1)) {
    const c = row.split(',')
    if (c[0] === '162') pop.set(c[1] + c[3], Number(c[14]))
  }
  const files = unzipSync(new Uint8Array(await download('gazetteer')))
  const text = Buffer.from(Object.values(files)[0]).toString('utf8')
  const out = []
  for (const row of text.split('\n').slice(1)) {
    const c = row.split('\t').map((s) => s.trim())
    if (c.length < 12) continue
    // Unincorporated places (CDPs) have no estimate; 0 keeps them for close-in zooms only.
    out.push([
      placeName(c[3]),
      round(Number(c[10]), 3),
      round(Number(c[11]), 3),
      pop.get(c[1]) ?? 0,
    ])
  }
  return out.sort((a, b) => b[3] - a[3])
}

const LEGAL_TYPE =
  /\s+(city|town|village|borough|CDP|municipality|township|comunidad|zona urbana|city and borough|plantation|corporation)$/i
const CONSOLIDATED =
  /\s+(metropolitan government|metro government|consolidated government|unified government|urban county)$/i

/**
 * Map-friendly place name: "Abbeville city" → "Abbeville",
 * "Indianapolis city (balance)" → "Indianapolis",
 * "Louisville/Jefferson County metro government (balance)" → "Louisville",
 * "Athens-Clarke County unified government (balance)" → "Athens",
 * "Macon-Bibb County" → "Macon". Ordinary hyphenated towns (Winston-Salem) are left alone.
 */
function placeName(raw) {
  const paren = /\s*\([^)]*\)$/
  let name = raw.replace(paren, '').replace(LEGAL_TYPE, '').replace(paren, '')
  const consolidated = CONSOLIDATED.test(name) || / County$/.test(name)
  name = name.replace(/\/.*$/, '').replace(CONSOLIDATED, '')
  if (consolidated) name = name.replace(/[-,].*$/, '')
  return name
}

async function main() {
  await mkdir(OUT, { recursive: true })
  const landData = await land()
  const countyData = await counties()
  const outputs = {
    'land.json': landData.topo,
    'counties.json': countyData.topo,
    'highways.json': await highways(),
    'labels.json': { states: landData.labels, places: await places() },
    'county-labels.json': countyData.labels,
  }
  for (const [file, data] of Object.entries(outputs)) {
    const json = JSON.stringify(data)
    await writeFile(join(OUT, file), json)
    console.log(`${file}: ${(json.length / 1024).toFixed(0)} KB`)
  }
}

await main()
