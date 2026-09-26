import { useState } from 'react'

import { ApiError } from '../api'
import { milesToKm } from '../lib/distanceBands'
import { FACTOR_LABELS, dayLabel, gapLabel, overlapPct, pct, rangeLabel } from '../lib/format'
import { scoreBand } from '../lib/pairs'
import type {
  Allocation,
  AllocationInputs,
  CoordinationBrief,
  CoordinationPair,
  PairProject,
  ProjectPatch,
} from '../types'
import { CostPanel } from './CostPanel'
import { SourceLink } from './SourceLink'

interface Props {
  pair: CoordinationPair | null
  colorOf: (p: PairProject) => string
  onGenerateBrief: (pair: CoordinationPair) => Promise<CoordinationBrief>
  /** Prices the pair; the cost section is hidden without it. */
  onAllocate?: (pair: CoordinationPair, inputs: AllocationInputs) => Promise<Allocation>
  onPatchProject?: (id: number, patch: ProjectPatch) => Promise<unknown>
}

function ProjectCard({ p, color }: { p: PairProject; color: string }) {
  return (
    <article className="project-card" style={{ borderTopColor: color }}>
      <p className="card-utility" style={{ color }}>
        {p.utility}
      </p>
      <h3>{p.name || 'Unnamed project'}</h3>
      <dl>
        <dt>Type</dt>
        <dd>{p.type ?? <em className="muted">unknown</em>}</dd>
        <dt>Voltage</dt>
        <dd>{p.voltage_kv ? `${p.voltage_kv} kV` : <em className="muted">unknown</em>}</dd>
        <dt>Location</dt>
        <dd>
          {p.location_ref ?? '—'}
          {p.approximate ? <span className="badge badge-approx">approximate</span> : null}
        </dd>
        <dt>Schedule</dt>
        <dd>{rangeLabel(p.start_date, p.end_date, p.start_precision, p.end_precision)}</dd>
        <dt>Confidence</dt>
        <dd>
          {pct(p.confidence)}
          {p.reviewed ? <span className="badge badge-ok">reviewed</span> : null}
        </dd>
      </dl>
      <SourceLink url={p.source_url} page={p.source_page} />
    </article>
  )
}

export function WhyFlaggedPanel({
  pair,
  colorOf,
  onGenerateBrief,
  onAllocate,
  onPatchProject,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  if (!pair) {
    return (
      <section className="why-panel empty-state" aria-label="Why flagged">
        <h2>Why flagged?</h2>
        <p>Select a pair from the list or map to compare the two projects.</p>
      </section>
    )
  }

  async function generate() {
    if (!pair) return
    setBusy(true)
    setError(null)
    try {
      await onGenerateBrief(pair)
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!pair?.brief) return
    await navigator.clipboard?.writeText(pair.brief.text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const factors = ['distance', 'overlap', 'type_similarity', 'voltage_similarity'] as const
  return (
    <section className="why-panel" aria-label="Why flagged">
      <header className="detail-head">
        <span className={`score-chip score-lg score-${scoreBand(pair.scores.composite)}`}>
          {pct(pair.scores.composite)}
        </span>
        <div>
          <h2>
            {pair.project_a.name || 'Unnamed'} <span className="muted">↔</span>{' '}
            {pair.project_b.name || 'Unnamed'}
          </h2>
          <p className="muted">
            {pair.project_a.utility} and {pair.project_b.utility} · why this pair was flagged
          </p>
        </div>
      </header>

      <div className="facts">
        <div className="fact">
          <span className="fact-value" data-testid="km">
            {milesToKm(pair.miles).toFixed(1)}
          </span>
          <span className="fact-label">km apart</span>
        </div>
        <div className="fact">
          <span className="fact-value" data-testid="overlap-pct">
            {pair.overlap_ratio == null ? '—' : overlapPct(pair.overlap_ratio)}
          </span>
          <span className="fact-label">build time shared</span>
        </div>
        <div className="fact">
          <span className="fact-value" data-testid="time-gap">
            {pair.time_gap_days == null ? '—' : gapLabel(pair.time_gap_days)}
          </span>
          <span className="fact-label">between in-service dates</span>
        </div>
        <div className="fact fact-wide">
          <span className="fact-value small" data-testid="overlap-days">
            {pair.window_start && pair.window_end
              ? `${dayLabel(pair.window_start)} – ${dayLabel(pair.window_end)} (${pair.overlap_days} d)`
              : pair.overlap_ratio == null
                ? 'Schedule unknown'
                : 'None'}
          </span>
          <span className="fact-label">both building</span>
        </div>
      </div>
      <p className="fact-note">
        Build time shared = days both projects are building ÷ days either one is. Where a plan
        gives only an in-service date, construction is assumed to take the 12 months before it.
      </p>

      <h3 className="section-title">Projects</h3>
      <div className="side-by-side">
        <ProjectCard p={pair.project_a} color={colorOf(pair.project_a)} />
        <ProjectCard p={pair.project_b} color={colorOf(pair.project_b)} />
      </div>

      <h3 className="section-title">Score breakdown</h3>
      <table className="factors" aria-label="Score factors">
        <tbody>
          {factors.map((f) => {
            const value = pair.scores[f]
            const indeterminate = pair.scores.indeterminate_factors.includes(f)
            return (
              <tr key={f}>
                <th scope="row">{FACTOR_LABELS[f]}</th>
                <td className="bar-cell">
                  <span className="bar">
                    <span className="bar-fill" style={{ width: pct(value) }} />
                  </span>
                </td>
                <td className="num">
                  {indeterminate ? (
                    <span className="muted" title="Missing data for this factor">
                      n/a
                    </span>
                  ) : (
                    value.toFixed(2)
                  )}
                </td>
              </tr>
            )
          })}
          <tr className="composite">
            <th scope="row">Composite</th>
            <td className="bar-cell">
              <span className="bar">
                <span className="bar-fill" style={{ width: pct(pair.scores.composite) }} />
              </span>
            </td>
            <td className="num">{pair.scores.composite.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>

      {onAllocate ? (
        <CostPanel pair={pair} onAllocate={onAllocate} onPatchProject={onPatchProject} />
      ) : null}

      <div className="brief">
        <header className="panel-head">
          <h3>Coordination brief</h3>
          {pair.brief?.stale ? (
            <span className="badge badge-warn" title="A project was edited after this brief">
              outdated
            </span>
          ) : null}
        </header>
        {pair.brief ? (
          <blockquote data-testid="brief-text">{pair.brief.text}</blockquote>
        ) : (
          <p className="no-brief" data-testid="no-brief">
            No coordination brief exists for this pair yet.
          </p>
        )}
        <div className="brief-actions">
          <button type="button" className="primary" onClick={generate} disabled={busy}>
            {busy ? 'Drafting…' : pair.brief ? 'Regenerate brief' : 'Generate brief'}
          </button>
          {pair.brief ? (
            <button type="button" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          ) : null}
        </div>
        {error ? (
          <p role="alert" className="error">
            {error}
          </p>
        ) : null}
      </div>
    </section>
  )
}
