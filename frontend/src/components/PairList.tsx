import { milesToKm } from '../lib/distanceBands'
import { pct } from '../lib/format'
import type { CoordinationPair } from '../types'

interface Props {
  pairs: CoordinationPair[]
  selectedId: string | null
  loading: boolean
  onSelect: (pair: CoordinationPair) => void
}

export function PairList({ pairs, selectedId, loading, onSelect }: Props) {
  return (
    <section className="pair-list" aria-label="Potential coordination opportunities">
      <header className="panel-head">
        <h2>Potential coordination opportunities</h2>
        <span className="count" aria-live="polite">
          {loading ? 'updating…' : pairs.length}
        </span>
      </header>
      <p className="muted">
        Built on public filings. Planned projects are not commitments to build.
      </p>
      {pairs.length === 0 && !loading ? (
        <p className="empty">No project pairs at these thresholds. Try ticking more distance bands or widening the date padding.</p>
      ) : null}
      <ol>
        {pairs.map((pair) => (
          <li key={pair.id}>
            <button
              type="button"
              className={`pair-row${pair.id === selectedId ? ' selected' : ''}`}
              aria-pressed={pair.id === selectedId}
              onClick={() => onSelect(pair)}
            >
              <span className="pair-score" title="Composite score">
                {pct(pair.scores.composite)}
              </span>
              <span className="pair-names">
                <span>{pair.project_a.name || 'Unnamed'}</span>
                <span className="muted">
                  {pair.project_a.utility} ↔ {pair.project_b.utility}
                </span>
                <span>{pair.project_b.name || 'Unnamed'}</span>
              </span>
              <span className="pair-meta">
                {milesToKm(pair.miles).toFixed(1)} km
                <br />
                {pair.overlap_days} d{pair.brief ? ' · ✉' : ''}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}
