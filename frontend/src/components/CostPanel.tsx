import { type FormEvent, useEffect, useState } from 'react'

import { ApiError } from '../api'
import { SCOPE_LABELS, money, pct } from '../lib/format'
import type {
  Allocation,
  AllocationInputs,
  CoordinationPair,
  CostEstimate,
  CostScope,
  PairProject,
  ProjectPatch,
} from '../types'

interface Props {
  pair: CoordinationPair
  onAllocate: (pair: CoordinationPair, inputs: AllocationInputs) => Promise<Allocation>
  /** Saves a project's cost inputs; the section is read-only without it. */
  onPatchProject?: (id: number, patch: ProjectPatch) => Promise<unknown>
}

const BASIS: Record<NonNullable<CostEstimate['basis']>, string> = {
  stated: 'Owner-stated cost',
  comparables: 'Benchmark + comparables',
  benchmark: 'Benchmark only',
}

const SIZE_SOURCE: Record<NonNullable<CostEstimate['size_source']>, string> = {
  stated: 'entered',
  text: 'from description',
  assumed: 'assumed',
  count: '',
}

function describe(e: unknown): string {
  return e instanceof ApiError ? e.body.message : String(e)
}

function sizeLabel(e: CostEstimate): string {
  if (e.size == null) return '—'
  if (e.size_unit === 'mi') return `${e.size} mi (${SIZE_SOURCE[e.size_source ?? 'text']})`
  return e.size === 1 ? '1 unit' : `${e.size} units`
}

function EstimateCell({ e }: { e: CostEstimate }) {
  if (!e.available) return <td className="muted">{e.reason}</td>
  return (
    <td>
      <strong className="cost-central">{money(e.central)}</strong>
      <span className="muted">
        {' '}
        {money(e.low)}–{money(e.high)}
      </span>
      {e.stated_outlier ? (
        <span className="badge badge-warn" title="Stated cost is outside the model's 80% range">
          check figure
        </span>
      ) : null}
    </td>
  )
}

/** Planner inputs for one project, saved to the project itself (PATCH). */
function ProjectInputs({
  p,
  estimate,
  onSave,
}: {
  p: PairProject
  estimate: CostEstimate
  onSave: (id: number, patch: ProjectPatch) => Promise<unknown>
}) {
  const [scope, setScope] = useState<string>(p.cost_scope ?? '')
  const [length, setLength] = useState(p.length_mi?.toString() ?? '')
  const [cost, setCost] = useState(p.stated_cost_musd?.toString() ?? '')
  const [year, setYear] = useState(p.cost_year?.toString() ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const label = p.name || `Project ${p.id}`

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    setSaving(true)
    setError(null)
    const num = (s: string) => (s.trim() === '' ? null : Number(s))
    try {
      await onSave(p.id, {
        cost_scope: (scope || null) as CostScope | null,
        length_mi: num(length),
        stated_cost_musd: num(cost),
        cost_year: num(year),
      })
    } catch (e) {
      setError(describe(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="cost-form" onSubmit={submit} aria-label={`Cost inputs for ${label}`}>
      <p className="cost-form-title">{label}</p>
      <label>
        Scope
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">
            From text{estimate.scope ? `: ${SCOPE_LABELS[estimate.scope]}` : ''}
          </option>
          {(Object.keys(SCOPE_LABELS) as CostScope[]).map((k) => (
            <option key={k} value={k}>
              {SCOPE_LABELS[k]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Line length (mi)
        <input inputMode="decimal" value={length} onChange={(e) => setLength(e.target.value)} />
      </label>
      <label>
        Stated cost ($M)
        <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
      </label>
      <label>
        Cost year
        <input inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} />
      </label>
      <button type="submit" disabled={saving}>
        {saving ? 'Saving…' : 'Save to project'}
      </button>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
    </form>
  )
}

const INPUT_FIELDS: { key: keyof AllocationInputs; label: string; side?: 'a' | 'b' }[] = [
  { key: 'joint_cost_musd', label: 'Joint project cost ($M)' },
  { key: 'usage_a_mw', label: 'Expected use (MW)', side: 'a' },
  { key: 'usage_b_mw', label: 'Expected use (MW)', side: 'b' },
  { key: 'benefit_a_musd', label: 'Quantified benefit ($M)', side: 'a' },
  { key: 'benefit_b_musd', label: 'Quantified benefit ($M)', side: 'b' },
]

export function CostPanel({ pair, onAllocate, onPatchProject }: Props) {
  const [inputs, setInputs] = useState<AllocationInputs>({})
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [result, setResult] = useState<Allocation | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The request that last settled; anything else means one is in flight.
  const [settled, setSettled] = useState<{ pair: CoordinationPair; inputs: AllocationInputs }>()
  const loading = settled?.pair !== pair || settled.inputs !== inputs

  useEffect(() => {
    let live = true
    onAllocate(pair, inputs)
      .then((r) => {
        if (!live) return
        setResult(r)
        setError(null)
      })
      .catch((e) => live && setError(describe(e)))
      .finally(() => live && setSettled({ pair, inputs }))
    return () => {
      live = false
    }
  }, [pair, inputs, onAllocate])

  function recalculate(ev: FormEvent) {
    ev.preventDefault()
    const next: AllocationInputs = {}
    for (const { key: k } of INPUT_FIELDS) {
      const v = draft[k]?.trim()
      if (v) next[k] = Number(v)
    }
    const share = draft.shareable_fraction?.trim()
    if (share) next.shareable_fraction = Number(share) / 100
    setInputs(next)
  }

  const a = pair.project_a
  const b = pair.project_b
  const nameA = a.utility
  const nameB = b.utility

  return (
    <section className="cost" aria-label="Cost and allocation">
      <h3 className="section-title">Cost &amp; allocation</h3>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      {!result ? (
        <p className="muted">{loading ? 'Estimating…' : null}</p>
      ) : (
        <>
          <table className="cost-table" aria-label="Stand-alone estimates">
            <thead>
              <tr>
                <th scope="col" />
                <th scope="col">{nameA}</th>
                <th scope="col">{nameB}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Stand-alone cost</th>
                <EstimateCell e={result.estimate_a} />
                <EstimateCell e={result.estimate_b} />
              </tr>
              {result.estimate_a.available || result.estimate_b.available ? (
                <>
                  <tr>
                    <th scope="row">Scope</th>
                    {[result.estimate_a, result.estimate_b].map((e) => (
                      <td key={e.project_id}>
                        {e.scope_label ?? '—'}
                        {e.scope_source === 'default' ? (
                          <span className="badge badge-warn" title="Scope not stated in the plan">
                            guessed
                          </span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Size</th>
                    {[result.estimate_a, result.estimate_b].map((e) => (
                      <td key={e.project_id}>
                        {sizeLabel(e)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Basis</th>
                    {[result.estimate_a, result.estimate_b].map((e) => (
                      <td key={e.project_id}>
                        {e.basis ? BASIS[e.basis] : '—'}
                        {e.comparable_count ? (
                          <span className="muted"> · {e.comparable_count} comparable</span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Confidence</th>
                    {[result.estimate_a, result.estimate_b].map((e) => (
                      <td key={e.project_id} data-testid={`confidence-${e.project_id}`}>
                        {e.confidence ?? '—'}
                        {e.spread != null ? (
                          <span className="muted"> (±{pct(e.spread)})</span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                </>
              ) : null}
            </tbody>
          </table>

          {result.available ? (
            <>
              <div className="facts">
                <div className="fact">
                  <span className="fact-value" data-testid="standalone-total">
                    {money((result.standalone_a ?? 0) + (result.standalone_b ?? 0))}
                  </span>
                  <span className="fact-label">built separately</span>
                </div>
                <div className="fact">
                  <span className="fact-value" data-testid="joint-cost">
                    {money(result.joint_cost)}
                  </span>
                  <span className="fact-label">
                    built together{result.joint_basis === 'planner' ? ' (entered)' : ' (modeled)'}
                  </span>
                </div>
                <div className="fact">
                  <span className="fact-value" data-testid="savings">
                    {money(result.savings)}
                  </span>
                  <span className="fact-label">saved by coordinating</span>
                </div>
              </div>

              <table className="cost-table splits" aria-label="Cost splits">
                <thead>
                  <tr>
                    <th scope="col">Split</th>
                    <th scope="col" className="num">
                      {nameA}
                    </th>
                    <th scope="col" className="num">
                      {nameB}
                    </th>
                    <th scope="col">Stand-alone test</th>
                  </tr>
                </thead>
                <tbody>
                  {result.splits.map((s) => (
                    <tr
                      key={s.key}
                      className={s.key === result.recommended ? 'recommended' : undefined}
                      title={s.note}
                    >
                      <th scope="row">
                        {s.label}
                        {s.key === result.recommended ? (
                          <span className="badge badge-ok">recommended</span>
                        ) : null}
                      </th>
                      <td className="num">
                        {money(s.pays_a)} <span className="muted">{pct(s.share_a)}</span>
                      </td>
                      <td className="num">
                        {money(s.pays_b)} <span className="muted">{pct(1 - s.share_a)}</span>
                      </td>
                      <td>
                        {s.within_standalone ? (
                          <span className="badge badge-ok">passes</span>
                        ) : (
                          <span className="badge badge-warn">fails</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="fact-note" data-testid="recommended-reason">
                {result.recommended_reason}
              </p>
            </>
          ) : result.reason ? (
            <p className="muted" data-testid="allocation-unavailable">
              No split: {result.reason}
            </p>
          ) : null}

          <details className="cost-details">
            <summary>Allocation inputs</summary>
            <form className="cost-form" onSubmit={recalculate} aria-label="Allocation inputs">
              {INPUT_FIELDS.map(({ key: k, label, side }) => (
                <label key={k}>
                  {side ? `${side === 'a' ? nameA : nameB}: ` : ''}
                  {label}
                  <input
                    inputMode="decimal"
                    value={draft[k] ?? ''}
                    onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                  />
                </label>
              ))}
              <label>
                Shareable share of the smaller project (%)
                <input
                  inputMode="decimal"
                  placeholder="30"
                  value={draft.shareable_fraction ?? ''}
                  onChange={(e) => setDraft({ ...draft, shareable_fraction: e.target.value })}
                />
              </label>
              <button type="submit" className="primary" disabled={loading}>
                Recalculate
              </button>
            </form>
          </details>

          {onPatchProject ? (
            <details className="cost-details">
              <summary>Project cost inputs</summary>
              <div className="side-by-side">
                <ProjectInputs p={a} estimate={result.estimate_a} onSave={onPatchProject} />
                <ProjectInputs p={b} estimate={result.estimate_b} onSave={onPatchProject} />
              </div>
            </details>
          ) : null}

          <details className="cost-details">
            <summary>Assumptions and comparables</summary>
            <ul className="assumptions">
              {[
                ...result.assumptions,
                ...result.estimate_a.assumptions.map((s) => `${nameA}: ${s}`),
                ...result.estimate_b.assumptions.map((s) => `${nameB}: ${s}`),
              ].map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            {[result.estimate_a, result.estimate_b].some((e) => e.comparables.length) ? (
              <table className="cost-table" aria-label="Comparable projects">
                <thead>
                  <tr>
                    <th scope="col">Comparable</th>
                    <th scope="col" className="num">
                      Cost
                    </th>
                    <th scope="col" className="num">
                      Weight
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[result.estimate_a, result.estimate_b].flatMap((e) =>
                    e.comparables.map((c) => (
                      <tr key={`${e.project_id}-${c.name}-${c.year}`}>
                        <th scope="row">
                          {c.name} <span className="muted">
                            {c.utility}, {c.year}
                            {c.actual ? '' : ', estimate'}
                          </span>
                        </th>
                        <td className="num">{money(c.cost_musd)}</td>
                        <td className="num">{c.weight.toFixed(2)}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            ) : null}
            <p className="fact-note">
              Planning-level estimates in {result.dollar_year} dollars. Benchmark unit costs are
              placeholders to calibrate with real cost history; costs owners state in their
              plans become comparables automatically.
            </p>
          </details>
        </>
      )}
    </section>
  )
}
