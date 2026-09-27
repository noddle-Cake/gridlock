import { useState } from 'react'

import { ApiError } from '../api'
import { type Draft, toDraft, diffDraft } from '../lib/draft'
import { OTHER_COLOR, pct, rangeLabel } from '../lib/format'
import { needsReview } from '../lib/review'
import type { Project, ProjectPatch, ProjectType } from '../types'
import { SourceLink } from './SourceLink'

const TYPES: ProjectType[] = ['substation', 'transmission line', 'generation']

interface Props {
  projects: Project[]
  threshold: number
  colors: Record<string, string>
  onPatch: (id: number, patch: ProjectPatch) => Promise<Project>
  /** Guests can look but not edit. */
  readOnly?: boolean
  onSignIn?: () => void
}

export function ReviewTable({
  projects,
  threshold,
  colors,
  onPatch,
  readOnly = false,
  onSignIn,
}: Props) {
  const [onlyReview, setOnlyReview] = useState(true)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [errors, setErrors] = useState<{ id: number; message: string; fields: string[] } | null>(
    null,
  )
  const [saving, setSaving] = useState(false)

  const flagged = (p: Project) => Boolean(p.ownership_review_required) ||
    (!p.reviewed && (needsReview(p.confidence, threshold) || p.requires_review))
  const pending = projects.filter((p) => flagged(p))
  const rows = onlyReview ? projects.filter((p) => flagged(p)) : projects

  function startEdit(p: Project) {
    setEditing(p.id)
    setDraft(toDraft(p))
    setErrors(null)
  }

  async function submit(p: Project, patch: ProjectPatch) {
    setSaving(true)
    setErrors(null)
    try {
      await onPatch(p.id, patch)
      return true
    } catch (e) {
      if (e instanceof ApiError) {
        setErrors({ id: p.id, message: e.body.message, fields: e.body.fields ?? [] })
      } else {
        setErrors({ id: p.id, message: String(e), fields: [] })
      }
      return false
    } finally {
      setSaving(false)
    }
  }

  async function save(p: Project) {
    if (!draft) return
    const patch = diffDraft(p, draft)
    if (Object.keys(patch).length === 0) {
      setEditing(null)
      return
    }
    if (await submit(p, patch)) setEditing(null)
  }

  const bad = (id: number, field: string) =>
    errors?.id === id && errors.fields.includes(field) ? 'invalid' : undefined

  function input(p: Project, field: keyof Draft, props: Record<string, unknown> = {}) {
    return (
      <input
        aria-label={`${field} for ${p.name ?? p.id}`}
        className={bad(p.id, field)}
        value={draft![field]}
        onChange={(e) => setDraft({ ...draft!, [field]: e.target.value })}
        {...props}
      />
    )
  }

  return (
    <section className="review" aria-label="Review extracted projects">
      <header className="panel-head">
        <h2>Review extracted projects</h2>
        <span className="count">{pending.length} need review</span>
        <label className="toggle">
          <input
            type="checkbox"
            checked={onlyReview}
            onChange={(e) => setOnlyReview(e.target.checked)}
          />
          Only show projects needing review
        </label>
      </header>
      {readOnly ? (
        <p className="sign-in-prompt inline">
          You're browsing as a guest.{' '}
          <button type="button" className="link-button" onClick={onSignIn}>
            Sign in
          </button>{' '}
          to correct projects or mark them reviewed.
        </p>
      ) : null}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Utility</th>
              <th>Project</th>
              <th>Type</th>
              <th>kV</th>
              <th>Location</th>
              <th>Lat, Lng</th>
              <th>Schedule</th>
              <th>Conf.</th>
              <th>Source</th>
              <th>Reviewed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={12} className="empty">
                  Nothing left to review.
                </td>
              </tr>
            ) : null}
            {rows.map((p) => {
              const low = needsReview(p.confidence, threshold)
              const isEditing = editing === p.id && draft
              return (
                <tr
                  key={p.id}
                  className={`${low ? 'needs-review' : ''}${p.reviewed ? ' reviewed' : ''}`}
                  data-testid={`review-row-${p.id}`}
                >
                  <td>
                    {low ? <span className="badge badge-warn">low confidence</span> : null}
                    {p.requires_review ? (
                      <span className="badge badge-warn">no location</span>
                    ) : null}
                    {p.ownership_review_required ? (
                      <span className="badge badge-warn" title="Corporate owner not verified: its opportunities are labelled unverified, or withheld if the ownership audit could not place it.">
                        ownership unverified
                      </span>
                    ) : null}
                    {!low && !p.requires_review && !p.ownership_review_required ? <span className="badge badge-ok">ok</span> : null}
                  </td>
                  <td>
                    <span className="swatch" style={{ background: colors[p.utility] ?? OTHER_COLOR }} />
                    {p.utility}
                  </td>
                  {isEditing ? (
                    <>
                      <td>{input(p, 'name')}</td>
                      <td>
                        <select
                          aria-label={`type for ${p.name ?? p.id}`}
                          className={bad(p.id, 'type')}
                          value={draft.type}
                          onChange={(e) => setDraft({ ...draft, type: e.target.value })}
                        >
                          <option value="">unknown</option>
                          {TYPES.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{input(p, 'voltage_kv', { inputMode: 'decimal', size: 5 })}</td>
                      <td>{input(p, 'location_ref')}</td>
                      <td className="latlng">
                        {input(p, 'lat', { inputMode: 'decimal', size: 8, placeholder: 'lat' })}
                        {input(p, 'lng', { inputMode: 'decimal', size: 8, placeholder: 'lng' })}
                      </td>
                      <td className="dates">
                        {input(p, 'start_date', { type: 'date' })}
                        {input(p, 'end_date', { type: 'date' })}
                      </td>
                    </>
                  ) : (
                    <>
                      <td>
                        <strong>{p.name || <em className="muted">unnamed</em>}</strong>
                        {p.raw_excerpt ? (
                          <details>
                            <summary>excerpt</summary>
                            <p className="excerpt">{p.raw_excerpt}</p>
                          </details>
                        ) : null}
                      </td>
                      <td>{p.type ?? <em className="muted">unknown</em>}</td>
                      <td className="num">{p.voltage_kv ?? '—'}</td>
                      <td>
                        {p.location_ref ?? '—'}
                        {p.approximate ? (
                          <span className="badge badge-approx">approx.</span>
                        ) : null}
                      </td>
                      <td className="num">
                        {p.lat != null ? `${p.lat.toFixed(3)}, ${p.lng!.toFixed(3)}` : '—'}
                      </td>
                      <td>
                        {rangeLabel(p.start_date, p.end_date, p.start_precision, p.end_precision)}
                      </td>
                    </>
                  )}
                  <td className="num">
                    <span className={low ? 'conf-low' : 'conf-ok'}>{pct(p.confidence)}</span>
                  </td>
                  <td>
                    <SourceLink url={p.source_url} page={p.source_page} />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Mark ${p.name ?? p.id} reviewed`}
                      checked={p.reviewed}
                      disabled={saving || readOnly}
                      onChange={(e) => submit(p, { reviewed: e.target.checked })}
                    />
                  </td>
                  <td className="actions">
                    {isEditing ? (
                      <>
                        <button
                          type="button"
                          className="primary"
                          onClick={() => save(p)}
                          disabled={saving}
                        >
                          Save
                        </button>
                        <button type="button" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </>
                    ) : readOnly ? null : (
                      <button type="button" onClick={() => startEdit(p)}>
                        Edit
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {errors ? (
        <p role="alert" className="error">
          {errors.message}
        </p>
      ) : null}
    </section>
  )
}
