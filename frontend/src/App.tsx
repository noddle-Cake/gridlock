import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from './api'
import { FilterMenu } from './components/FilterMenu'
import { MapView } from './components/MapView'
import { PairList } from './components/PairList'
import { ReviewTable } from './components/ReviewTable'
import { DEFAULT_PAD, DEFAULT_RADIUS, ThresholdControls } from './components/ThresholdControls'
import { TimelineView } from './components/TimelineView'
import { UploadPanel } from './components/UploadPanel'
import { UtilityFilter } from './components/UtilityFilter'
import { WhyFlaggedPanel } from './components/WhyFlaggedPanel'
import { utilityColors } from './lib/format'
import {
  type SortKey,
  type ViewBounds,
  bestPairFor,
  filterPairs,
  pairsInView,
  sortPairs,
} from './lib/pairs'
import { DEFAULT_CONFIDENCE_THRESHOLD, needsReview } from './lib/review'
import type { CoordinationPair, LineCollection, Project, ProjectPatch } from './types'

const REQUERY_DEBOUNCE_MS = 150

type Tab = 'radar' | 'review'

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [pairs, setPairs] = useState<CoordinationPair[]>([])
  const [radius, setRadius] = useState(DEFAULT_RADIUS)
  const [pad, setPad] = useState(DEFAULT_PAD)
  const [confidenceThreshold, setConfidenceThreshold] = useState(DEFAULT_CONFIDENCE_THRESHOLD)
  const [selectedId, setSelectedId] = useState<string | null>(pairFromHash)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hiddenUtilities, setHiddenUtilities] = useState<Set<string>>(() => new Set())
  const [sort, setSort] = useState<SortKey>('score')
  const [limitToView, setLimitToView] = useState(true)
  const [viewBounds, setViewBounds] = useState<ViewBounds | null>(null)
  const [showTimeline, setShowTimeline] = useState(true)
  const [tab, setTab] = useState<Tab>('radar')
  const [loadingPairs, setLoadingPairs] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lines, setLines] = useState<LineCollection | null>(null)
  const [linesFailed, setLinesFailed] = useState(false)
  const [version, setVersion] = useState(0)
  const requestSeq = useRef(0)

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    api
      .projects()
      .then(setProjects)
      .catch((e) => setError(describe(e)))
  }, [version])

  // Existing transmission lines are a static backdrop: fetch once. A failure only hides
  // the layer (with a note on the map); it never blocks the planning views.
  useEffect(() => {
    api
      .lines()
      .then(setLines)
      .catch(() => setLinesFailed(true))
  }, [])

  // Re-query matching whenever a threshold slider moves (Req 10.3, 10.4).
  useEffect(() => {
    const seq = ++requestSeq.current
    const timer = setTimeout(() => {
      setLoadingPairs(true)
      api
        .overlaps(radius, pad)
        .then((res) => {
          if (seq !== requestSeq.current) return // a newer slider value won
          setPairs(res.pairs)
          setError(null)
        })
        .catch((e) => seq === requestSeq.current && setError(describe(e)))
        .finally(() => seq === requestSeq.current && setLoadingPairs(false))
    }, REQUERY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [radius, pad, version])

  // One color per company across planned projects and existing-line owners, so a
  // utility reads the same on both layers.
  const colors = useMemo(
    () =>
      utilityColors([
        ...projects.map((p) => p.utility),
        ...(lines?.features.flatMap((f) => f.properties.owner_norm ?? []) ?? []),
      ]),
    [projects, lines],
  )
  const utilities = useMemo(
    () => [...new Set(projects.map((p) => p.utility))].sort((a, b) => a.localeCompare(b)),
    [projects],
  )
  const shownProjects = useMemo(
    () => projects.filter((p) => !hiddenUtilities.has(p.utility)),
    [projects, hiddenUtilities],
  )
  // Search and utility filters apply to the map and the list alike; the map-view limit
  // applies only to the list, so the map keeps showing everything that matches.
  const shownPairs = useMemo(
    () => sortPairs(filterPairs(pairs, { query, hiddenUtilities }), sort),
    [pairs, query, hiddenUtilities, sort],
  )
  const listPairs = useMemo(
    () => (limitToView ? pairsInView(shownPairs, viewBounds) : shownPairs),
    [shownPairs, limitToView, viewBounds],
  )
  const selectedPair = pairs.find((p) => p.id === selectedId) ?? null
  const hoveredPair = pairs.find((p) => p.id === hoveredId) ?? null
  const reviewCount = projects.filter(
    (p) => !p.reviewed && (needsReview(p.confidence, confidenceThreshold) || p.requires_review),
  ).length

  // Prev/next in the detail view walks the list as it was when the pair was opened. The
  // map flying in to the pair must not shrink that list, so the view limit freezes while
  // a pair is open.
  const selectedRef = useRef(selectedId)
  useEffect(() => {
    selectedRef.current = selectedId
  }, [selectedId])
  const onBoundsChange = useCallback((b: ViewBounds) => {
    if (!selectedRef.current) setViewBounds(b)
  }, [])

  const selectProject = useCallback(
    (p: Project) => setSelectedId(bestPairFor(p, shownPairs)?.id ?? null),
    [shownPairs],
  )
  const hoverProject = useCallback(
    (p: Project | null) => setHoveredId(p ? (bestPairFor(p, shownPairs)?.id ?? null) : null),
    [shownPairs],
  )

  const index = selectedPair ? listPairs.findIndex((p) => p.id === selectedPair.id) : -1
  function step(d: number) {
    const next = listPairs[index + d]
    if (next) setSelectedId(next.id)
  }

  // The open pair lives in the URL hash so a pair can be linked and survives a reload.
  useEffect(() => {
    const hash = selectedId ? `#pair=${encodeURIComponent(selectedId)}` : ''
    if (window.location.hash !== hash) {
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}${hash}`)
    }
  }, [selectedId])

  // Escape closes the open pair, like closing a listing.
  useEffect(() => {
    if (!selectedId) return
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement).closest('input, textarea, select')) return
      if (e.key === 'Escape') setSelectedId(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectedId])

  async function generateBrief(pair: CoordinationPair) {
    const brief = await api.brief(pair.id, radius, pad)
    setPairs((prev) => prev.map((p) => (p.id === pair.id ? { ...p, brief } : p)))
    return brief
  }

  async function patchProject(id: number, patch: ProjectPatch) {
    const updated = await api.patchProject(id, patch)
    setProjects((prev) => prev.map((p) => (p.id === id ? updated : p)))
    refresh() // geom/date edits change which pairs qualify
    return updated
  }

  return (
    <div className={`app app-${tab}`}>
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={26} height={26} />
          <div>
            <h1>GridMerge</h1>
            <p>Coordination radar for utility capital plans</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Views">
          <button
            type="button"
            className={tab === 'radar' ? 'active' : ''}
            aria-pressed={tab === 'radar'}
            onClick={() => setTab('radar')}
          >
            Radar
          </button>
          <button
            type="button"
            className={tab === 'review' ? 'active' : ''}
            aria-pressed={tab === 'review'}
            onClick={() => setTab('review')}
          >
            Review <span className="pill">{reviewCount}</span>
          </button>
        </nav>
        <div className="exports">
          <a href={api.exportUrl('csv', radius, pad)} download>
            Export CSV
          </a>
          <a href={api.exportUrl('pdf', radius, pad)} download>
            Export PDF
          </a>
        </div>
      </header>

      <div className="filterbar">
        <label className="search">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          <input
            type="search"
            placeholder="Search project, utility, or place"
            aria-label="Search pairs"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="chips">
          <ThresholdControls
            radius={radius}
            pad={pad}
            confidenceThreshold={confidenceThreshold}
            onRadius={setRadius}
            onPad={setPad}
            onConfidenceThreshold={setConfidenceThreshold}
          />
          <UtilityFilter
            utilities={utilities}
            hidden={hiddenUtilities}
            colors={colors}
            onChange={setHiddenUtilities}
          />
        </div>
        <FilterMenu label="Upload plan" align="right" className="upload-menu">
          <UploadPanel onPlanComplete={refresh} />
        </FilterMenu>
      </div>

      {error ? (
        <p role="alert" className="error banner">
          {error}
        </p>
      ) : null}

      {tab === 'radar' ? (
        <main className="split">
          <div className="viz">
            <MapView
              projects={shownProjects}
              pairs={shownPairs}
              selectedPair={selectedPair}
              hoveredPair={hoveredPair}
              colors={colors}
              lines={lines}
              linesFailed={linesFailed}
              onSelectProject={selectProject}
              onSelectPair={(p) => setSelectedId(p.id)}
              onHoverProject={hoverProject}
              onBoundsChange={onBoundsChange}
            />
            <section className={`timeline-dock${showTimeline ? '' : ' collapsed'}`}>
              <button
                type="button"
                className="dock-toggle"
                aria-expanded={showTimeline}
                onClick={() => setShowTimeline((v) => !v)}
              >
                <span className="dock-title">Schedule</span>
                <span className="muted">
                  {showTimeline ? 'Hide timeline' : 'Show timeline'}
                </span>
              </button>
              <div className="timeline-body" hidden={!showTimeline}>
                <TimelineView
                  projects={shownProjects}
                  pairs={shownPairs}
                  selectedPair={selectedPair}
                  colors={colors}
                  onSelectProject={selectProject}
                />
              </div>
            </section>
          </div>
          <aside className="panel" aria-label="Pairs">
            {selectedPair ? (
              <div className="detail">
                <nav className="detail-nav" aria-label="Pair navigation">
                  <button type="button" className="back" onClick={() => setSelectedId(null)}>
                    ← Back to list
                  </button>
                  {index >= 0 ? (
                    <span className="detail-pos">
                      <button
                        type="button"
                        aria-label="Previous pair"
                        disabled={index <= 0}
                        onClick={() => step(-1)}
                      >
                        ‹
                      </button>
                      <span className="count">
                        {index + 1} of {listPairs.length}
                      </span>
                      <button
                        type="button"
                        aria-label="Next pair"
                        disabled={index >= listPairs.length - 1}
                        onClick={() => step(1)}
                      >
                        ›
                      </button>
                    </span>
                  ) : null}
                </nav>
                <WhyFlaggedPanel
                  key={selectedPair.id}
                  pair={selectedPair}
                  colors={colors}
                  onGenerateBrief={generateBrief}
                />
              </div>
            ) : (
              <PairList
                pairs={listPairs}
                totalCount={shownPairs.length}
                selectedId={selectedId}
                hoveredId={hoveredId}
                loading={loadingPairs}
                colors={colors}
                sort={sort}
                onSort={setSort}
                limitToView={limitToView}
                onLimitToView={setLimitToView}
                onSelect={(p) => {
                  setHoveredId(null)
                  setSelectedId(p.id)
                }}
                onHover={(p) => setHoveredId(p?.id ?? null)}
              />
            )}
          </aside>
        </main>
      ) : (
        <main className="review-layout">
          <ReviewTable
            projects={projects}
            threshold={confidenceThreshold}
            colors={colors}
            onPatch={patchProject}
          />
        </main>
      )}
    </div>
  )
}

function pairFromHash(): string | null {
  const m = /^#pair=(.+)$/.exec(window.location.hash)
  return m ? decodeURIComponent(m[1]) : null
}

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.body.message
  return `Could not reach the GridMerge API (${String(e)}). Is the backend running?`
}
