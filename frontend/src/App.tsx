import {
  type UIEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { ApiError, api } from './api'
import { AskPanel, type AskState } from './components/AskPanel'
import type { Account } from './components/AuthGate'
import { FilterMenu } from './components/FilterMenu'
import { JobTray } from './components/JobTray'
import { type MapFocus, MapView } from './components/MapView'
import { PairList } from './components/PairList'
import { ReviewTable } from './components/ReviewTable'
import { SmartSearch } from './components/SmartSearch'
import { ThresholdControls } from './components/ThresholdControls'
import { UploadPanel } from './components/UploadPanel'
import { UtilityFilter } from './components/UtilityFilter'
import { WhyFlaggedPanel } from './components/WhyFlaggedPanel'
import { accountCompany, pairPartners } from './lib/account'
import { ALL_BANDS, MAX_RADIUS_MILES, type BandId } from './lib/distanceBands'
import { PALETTE, num, utilityColors } from './lib/format'
import { type ColorBy, colorLegend, projectColor } from './lib/mapStyle'
import {
  type SortKey,
  type ViewBounds,
  bestPairFor,
  filterPairs,
  filterProjects,
  pairScope,
  pairsInView,
  sortPairs,
} from './lib/pairs'
import { DEFAULT_CONFIDENCE_THRESHOLD, inReviewQueue } from './lib/review'
import { type AiJob, useAiJobs } from './lib/useAiJobs'
import { useColorScheme } from './lib/useColorScheme'
import { useSearch } from './lib/useSearch'
import type {
  CoordinationPair,
  MatchRules,
  PairProject,
  Project,
  ProjectPatch,
  SearchResponse,
} from './types'

const REQUERY_DEBOUNCE_MS = 150

type Tab = 'radar' | 'review'

/** `account` is the signed-in user (AuthGate); null when the server has no sign-in. */
export default function App({ account = null }: { account?: Account | null }) {
  const [projects, setProjects] = useState<Project[]>([])
  // The first project load decides the utility focus, which scopes the pair query.
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [pairs, setPairs] = useState<CoordinationPair[]>([])
  const [rules, setRules] = useState<MatchRules | null>(null)
  const [bands, setBands] = useState<BandId[]>(ALL_BANDS)
  const [confidenceThreshold, setConfidenceThreshold] = useState(DEFAULT_CONFIDENCE_THRESHOLD)
  const [selectedId, setSelectedId] = useState<string | null>(pairFromHash)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hiddenUtilities, setHiddenUtilities] = useState<Set<string>>(() => new Set())
  const [sort, setSort] = useState<SortKey>('score')
  const [limitToView, setLimitToView] = useState(true)
  const [viewBounds, setViewBounds] = useState<ViewBounds | null>(null)
  const [tab, setTab] = useState<Tab>('radar')
  const [loadingPairs, setLoadingPairs] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  // Company first: the point of the view is telling two utilities' plans apart.
  const [colorBy, setColorBy] = useState<ColorBy>('utility')
  const [focus, setFocus] = useState<MapFocus | null>(null)
  // Set by Enter or a company/place pick (and cleared by typing): frame the matches once
  // /search answers for the text.
  const [frameSeq, setFrameSeq] = useState<number | null>(null)
  // The Ask GridMerge answer on screen (a job id), or null when the panel is closed.
  const [askJobId, setAskJobId] = useState<number | null>(null)
  const ai = useAiJobs()
  const scheme = useColorScheme()
  const requestSeq = useRef(0)
  const focusSeq = useRef(0)
  const search = useSearch(query)

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    // Opens on every loaded utility (nationwide). "Only Dominion SC ↔ Georgia Power" is
    // in the utility menu; opening on it showed an empty list once matches had to overlap in
    // time, as none of their future work does.
    api
      .projects()
      .then(setProjects)
      .catch((e) => setError(describe(e)))
      .finally(() => setProjectsLoaded(true))
  }, [version])

  const utilities = useMemo(
    () => [...new Set(projects.map((p) => p.utility))].sort((a, b) => a.localeCompare(b)),
    [projects],
  )
  // With only some utilities shown, the pair query asks for just theirs (all within one
  // string so the effect below re-runs on a change of content, not of identity).
  const scope = pairScope(utilities, hiddenUtilities)
  const scopeKey = scope ? JSON.stringify(scope) : ''

  // Re-query matching whenever a threshold control or the utility scope changes (Req 10.3,
  // 10.4). The first load goes out at once; only later control changes are debounced.
  useEffect(() => {
    if (!projectsLoaded) return
    const seq = ++requestSeq.current
    const only: string[] | undefined = scopeKey ? JSON.parse(scopeKey) : undefined
    const timer = setTimeout(() => {
      if (only?.length === 0) {
        setPairs([]) // every utility hidden: nothing to ask for
        return
      }
      setLoadingPairs(true)
      api
        .overlaps(MAX_RADIUS_MILES, bands, only)
        .then((res) => {
          if (seq !== requestSeq.current) return // a newer control value won
          setPairs(res.pairs)
          setRules({ planning_from: res.planning_from, min_overlap_days: res.min_overlap_days })
          setError(null)
        })
        .catch((e) => seq === requestSeq.current && setError(describe(e)))
        .finally(() => seq === requestSeq.current && setLoadingPairs(false))
    }, seq === 1 ? 0 : REQUERY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [bands, version, scopeKey, projectsLoaded])

  // The signed-in planner's own company (e.g. FPL for an @fpl.com account), if known.
  const ownCompany = useMemo(
    () => accountCompany(account?.username, utilities),
    [account?.username, utilities],
  )
  // Only a few companies get their own colour; the rest share a neutral "other". The
  // user's company always has one, and the utilities on screen (when few enough are chosen)
  // or else the companies it shares pairs with take the next, most distinct colours.
  const colors = useMemo(() => {
    const shown = utilities.filter((u) => !hiddenUtilities.has(u))
    const filtered = hiddenUtilities.size > 0 && shown.length <= PALETTE.length
    const first = filtered ? shown : ownCompany ? pairPartners(pairs, ownCompany) : []
    return utilityColors(
      projects.map((p) => p.utility),
      first,
      ownCompany,
    )
  }, [projects, utilities, hiddenUtilities, pairs, ownCompany])
  // Map markers and panel swatches share one encoding, so a card always matches its dot.
  const colorOf = useCallback(
    (p: PairProject) => projectColor(p, colorBy, colors, scheme),
    [colorBy, colors, scheme],
  )
  const utilityCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const p of projects) m.set(p.utility, (m.get(p.utility) ?? 0) + 1)
    return m
  }, [projects])
  const shownProjects = useMemo(
    () => projects.filter((p) => !hiddenUtilities.has(p.utility)),
    [projects, hiddenUtilities],
  )
  // Search and utility filters apply to the map and the list alike; the map-view limit
  // applies only to the list, so the map keeps showing everything that matches.
  const matchIds = useMemo(
    () => (search.result ? new Set(search.result.project_ids) : null),
    [search.result],
  )
  const shownPairs = useMemo(
    () => sortPairs(filterPairs(pairs, { query, hiddenUtilities, matchIds }), sort),
    [pairs, query, hiddenUtilities, matchIds, sort],
  )
  const listPairs = useMemo(
    () => (limitToView ? pairsInView(shownPairs, viewBounds) : shownPairs),
    [shownPairs, limitToView, viewBounds],
  )
  const legend = useMemo(
    () =>
      colorLegend(
        shownProjects.filter((p) => p.lat != null && p.lng != null),
        colorBy,
        colors,
        scheme,
        ownCompany,
      ),
    [shownProjects, colorBy, colors, scheme, ownCompany],
  )
  const selectedPair = pairs.find((p) => p.id === selectedId) ?? null
  const hoveredPair = pairs.find((p) => p.id === hoveredId) ?? null
  // Review follows the same utility and search filters as the radar.
  const reviewProjects = useMemo(
    () => filterProjects(projects, { query, hiddenUtilities, matchIds }),
    [projects, query, hiddenUtilities, matchIds],
  )
  const reviewCount = reviewProjects.filter((p) => inReviewQueue(p, confidenceThreshold)).length

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

  const selectPair = useCallback((p: CoordinationPair) => setSelectedId(p.id), [])

  const flyTo = useCallback((bounds: MapFocus['bounds']) => {
    focusSeq.current += 1
    setFocus({ bounds, seq: focusSeq.current })
  }, [])

  // The newest of: a project flown to, or a search framed once its answer is in.
  const searchBounds = search.result?.bounds
  const mapFocus = useMemo<MapFocus | null>(() => {
    const framed =
      frameSeq != null && searchBounds ? { bounds: boundsOf(searchBounds), seq: frameSeq } : null
    return framed && (!focus || framed.seq > focus.seq) ? framed : focus
  }, [frameSeq, searchBounds, focus])

  function editQuery(text: string) {
    if (/^\d{5}(?:-\d{4})?$/.test(text.trim())) {
      applySearch(text)
      return
    }
    setQuery(text)
    setFrameSeq(null)
  }

  /**
   * Keep `text` (or the current text) as the search and frame what it matches. A search
   * spans every company, so it lifts the utility filter (e.g. the opening two-utility
   * focus) rather than hiding what it found.
   */
  function applySearch(text?: string) {
    if (text !== undefined) setQuery(text)
    if (hiddenUtilities.size) setHiddenUtilities(new Set())
    setTab('radar')
    setSelectedId(null)
    focusSeq.current += 1
    setFrameSeq(focusSeq.current)
  }

  /** A project picked from search or cited by the AI: open its best pair, else fly to it. */
  const openProject = useCallback(
    (p: PairProject) => {
      setTab('radar')
      const pair = bestPairFor(p, shownPairs) ?? bestPairFor(p, pairs)
      if (pair) setSelectedId(pair.id)
      else if (p.lat != null && p.lng != null) {
        setSelectedId(null)
        flyTo([
          [p.lat - 0.05, p.lng - 0.05],
          [p.lat + 0.05, p.lng + 0.05],
        ])
      }
    },
    [shownPairs, pairs, flyTo],
  )

  // AI work runs as background jobs (lib/useAiJobs.ts): leaving its panel doesn't stop it,
  // and a result that lands off screen waits in the header tray.
  const view = useRef({ tab, selectedId, askJobId })
  useEffect(() => {
    view.current = { tab, selectedId, askJobId }
  }, [tab, selectedId, askJobId])
  const onScreen = useCallback((j: Pick<AiJob, 'id' | 'kind' | 'pairId'>) => {
    const v = view.current
    if (v.tab !== 'radar') return false
    return j.kind === 'ask' ? v.askJobId === j.id : v.selectedId === j.pairId
  }, [])
  // Arriving at a finished job's result by any route (the list, a link) counts as seeing it.
  const { jobs: aiJobs, markSeen } = ai
  useEffect(() => {
    for (const j of aiJobs) if (j.unseen && onScreen(j)) markSeen(j.id)
  }, [aiJobs, markSeen, onScreen, tab, selectedId, askJobId])

  // Guests browse read-only: AI features and edits send them to sign in instead.
  const guest = account?.guest ?? false
  const signIn = account?.onSignIn

  function runAsk(question: string) {
    const q = question.trim()
    if (!q) return
    if (guest) return signIn?.()
    const id: number = ai.start({ kind: 'ask', title: q, question: q }, () => api.ask(q), {
      onScreen: () => onScreen({ id, kind: 'ask' }),
      describe,
    })
    setTab('radar')
    setAskJobId(id)
  }

  const askJob = aiJobs.find((j) => j.id === askJobId)
  const ask: AskState | null = !askJob
    ? null
    : askJob.status === 'running'
      ? { status: 'loading', question: askJob.question ?? askJob.title }
      : askJob.status === 'done' && askJob.answer
        ? { status: 'done', question: askJob.question ?? askJob.title, response: askJob.answer }
        : { status: 'error', question: askJob.question ?? askJob.title, message: askJob.error ?? '' }

  /** Close the answer panel. A question still being answered keeps going in the tray. */
  function closeAsk() {
    if (askJob) ai.remove(askJob.id)
    setAskJobId(null)
  }

  function openJob(j: AiJob) {
    setTab('radar')
    if (j.kind === 'ask') setAskJobId(j.id)
    else if (j.pairId) setSelectedId(j.pairId)
    ai.markSeen(j.id)
  }

  // The list and the pair detail share one scrolling panel. A pair opens at its top, and
  // "Back to list" returns to where the list was instead of the detail's scroll offset.
  const panelRef = useRef<HTMLElement>(null)
  const listScroll = useRef(0)
  useLayoutEffect(() => {
    const el = panelRef.current
    if (el) el.scrollTop = selectedId ? 0 : listScroll.current
  }, [selectedId])
  const onPanelScroll = useCallback((e: UIEvent<HTMLElement>) => {
    if (!selectedRef.current) listScroll.current = e.currentTarget.scrollTop
  }, [])

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

  function generateBrief(pair: CoordinationPair) {
    const names = `${pair.project_a.name || 'Unnamed'} ↔ ${pair.project_b.name || 'Unnamed'}`
    ai.start(
      { kind: 'brief', title: names, pairId: pair.id },
      () => api.brief(pair.id, MAX_RADIUS_MILES),
      {
        onDone: (brief) =>
          setPairs((prev) => prev.map((p) => (p.id === pair.id ? { ...p, brief } : p))),
        onScreen: () => onScreen({ id: 0, kind: 'brief', pairId: pair.id }),
        describe,
      },
    )
  }
  // The open pair's latest brief job: drives its "Drafting…" button and error, wherever
  // the planner went in between.
  const briefJob = selectedPair
    ? aiJobs.findLast((j) => j.kind === 'brief' && j.pairId === selectedPair.id)
    : undefined

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
            Review <span className="pill">{num(reviewCount)}</span>
          </button>
        </nav>
        <JobTray jobs={aiJobs} onOpen={openJob} onDismiss={(j) => ai.markSeen(j.id)} />
        <div className="exports">
          <a href={api.exportUrl('csv', MAX_RADIUS_MILES, bands, scope)} download>
            Export CSV
          </a>
          <a href={api.exportUrl('pdf', MAX_RADIUS_MILES, bands, scope)} download>
            Export PDF
          </a>
          {account?.guest ? (
            <>
              <span className="guest-badge" title="Browsing without signing in: no AI or edits">
                Guest
              </span>
              <button type="button" className="sign-out" onClick={account.onSignIn}>
                Sign in
              </button>
            </>
          ) : account ? (
            <button
              type="button"
              className="sign-out"
              title={account.username ? `Signed in as ${account.username}` : undefined}
              onClick={account.onSignOut}
            >
              Sign out
            </button>
          ) : null}
        </div>
      </header>

      <div className="filterbar">
        <SmartSearch
          value={query}
          onChange={editQuery}
          result={search.result}
          loading={search.loading}
          error={search.error}
          onApply={() => applySearch()}
          onPickCompany={(c) => applySearch(c.utility)}
          onPickLocation={(l) => applySearch(l.kind === 'zip' ? l.code : l.label)}
          onPickProject={openProject}
          onAsk={runAsk}
          aiLocked={guest}
        />
        <div className="chips">
          <ThresholdControls
            bands={bands}
            confidenceThreshold={confidenceThreshold}
            onBands={setBands}
            onConfidenceThreshold={setConfidenceThreshold}
          />
          <UtilityFilter
            utilities={utilities}
            counts={utilityCounts}
            hidden={hiddenUtilities}
            colors={colors}
            onChange={setHiddenUtilities}
          />
        </div>
        <FilterMenu label="Upload plan" align="right" className="upload-menu">
          {guest ? (
            <div className="sign-in-prompt">
              <p>Uploading a plan extracts its projects with AI, so it needs a sign-in.</p>
              <button type="button" className="primary" onClick={signIn}>
                Sign in to upload
              </button>
            </div>
          ) : (
            <UploadPanel onPlanComplete={refresh} />
          )}
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
              colorOf={colorOf}
              colorBy={colorBy}
              onColorBy={setColorBy}
              legend={legend}
              scheme={scheme}
              onSelectProject={selectProject}
              onSelectPair={selectPair}
              onHoverProject={hoverProject}
              onBoundsChange={onBoundsChange}
              focus={mapFocus}
            />
          </div>
          <aside className="panel" aria-label="Pairs" ref={panelRef} onScroll={onPanelScroll}>
            {ask ? (
              <AskPanel
                state={ask}
                onSelectProject={openProject}
                onClose={closeAsk}
                onRetry={() => runAsk(ask.question)}
              />
            ) : null}
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
                        {num(index + 1)} of {num(listPairs.length)}
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
                  colorOf={colorOf}
                  onGenerateBrief={guest ? () => signIn?.() : generateBrief}
                  briefLocked={guest}
                  briefRunning={briefJob?.status === 'running'}
                  briefError={briefJob?.status === 'error' ? briefJob.error : undefined}
                />
              </div>
            ) : (
              <PairList
                pairs={listPairs}
                rules={rules}
                totalCount={shownPairs.length}
                selectedId={selectedId}
                hoveredId={hoveredId}
                loading={loadingPairs}
                colorOf={colorOf}
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
            projects={reviewProjects}
            threshold={confidenceThreshold}
            colors={colors}
            onPatch={patchProject}
            readOnly={guest}
            onSignIn={signIn}
          />
        </main>
      )}
    </div>
  )
}

/** A /search [south, west, north, east] box as Leaflet corner points. */
function boundsOf(b: NonNullable<SearchResponse['bounds']>): MapFocus['bounds'] {
  const [south, west, north, east] = b
  return [
    [south, west],
    [north, east],
  ]
}

function pairFromHash(): string | null {
  const m = /^#pair=(.+)$/.exec(window.location.hash)
  return m ? decodeURIComponent(m[1]) : null
}

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.body.message
  return `Could not reach the GridMerge API (${String(e)}). Is the backend running?`
}
