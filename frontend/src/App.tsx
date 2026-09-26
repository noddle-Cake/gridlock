import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from './api'
import { MapView } from './components/MapView'
import { PairList } from './components/PairList'
import { ReviewTable } from './components/ReviewTable'
import { ThresholdControls } from './components/ThresholdControls'
import { TimelineView } from './components/TimelineView'
import { UploadPanel } from './components/UploadPanel'
import { WhyFlaggedPanel } from './components/WhyFlaggedPanel'
import { utilityColors } from './lib/format'
import { DEFAULT_CONFIDENCE_THRESHOLD, needsReview } from './lib/review'
import type { CoordinationPair, Project, ProjectPatch } from './types'

const DEFAULT_RADIUS = 25
const DEFAULT_PAD = 30
const REQUERY_DEBOUNCE_MS = 150

type Tab = 'radar' | 'review'

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [pairs, setPairs] = useState<CoordinationPair[]>([])
  const [radius, setRadius] = useState(DEFAULT_RADIUS)
  const [pad, setPad] = useState(DEFAULT_PAD)
  const [confidenceThreshold, setConfidenceThreshold] = useState(DEFAULT_CONFIDENCE_THRESHOLD)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('radar')
  const [loadingPairs, setLoadingPairs] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const requestSeq = useRef(0)

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    api
      .projects()
      .then(setProjects)
      .catch((e) => setError(describe(e)))
  }, [version])

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

  const colors = useMemo(() => utilityColors(projects.map((p) => p.utility)), [projects])
  const selectedPair = pairs.find((p) => p.id === selectedId) ?? null
  const reviewCount = projects.filter(
    (p) => !p.reviewed && (needsReview(p.confidence, confidenceThreshold) || p.requires_review),
  ).length

  const selectProject = useCallback(
    (p: Project) => {
      const best = pairs.find((pair) => pair.project_a.id === p.id || pair.project_b.id === p.id)
      setSelectedId(best?.id ?? null)
    },
    [pairs],
  )

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
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
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

      <div className="toolbar">
        <UploadPanel onPlanComplete={refresh} />
        <ThresholdControls
          radius={radius}
          pad={pad}
          confidenceThreshold={confidenceThreshold}
          onRadius={setRadius}
          onPad={setPad}
          onConfidenceThreshold={setConfidenceThreshold}
        />
      </div>

      {error ? (
        <p role="alert" className="error banner">
          {error}
        </p>
      ) : null}

      {tab === 'radar' ? (
      <main className="layout">
        <div className="viz">
          <MapView
            projects={projects}
            pairs={pairs}
            selectedPair={selectedPair}
            colors={colors}
            onSelectProject={selectProject}
          />
          <TimelineView
            projects={projects}
            pairs={pairs}
            selectedPair={selectedPair}
            colors={colors}
            onSelectProject={selectProject}
          />
        </div>
        <aside className="side">
          <PairList
            pairs={pairs}
            selectedId={selectedId}
            loading={loadingPairs}
            onSelect={(p) => setSelectedId(p.id)}
          />
          <WhyFlaggedPanel
            key={selectedPair?.id ?? 'none'}
            pair={selectedPair}
            colors={colors}
            onGenerateBrief={generateBrief}
          />
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

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.body.message
  return `Could not reach the GridMerge API (${String(e)}). Is the backend running?`
}
