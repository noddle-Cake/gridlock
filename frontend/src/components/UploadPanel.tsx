import { type FormEvent, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../api'
import { plural } from '../lib/format'
import type { Plan } from '../types'

interface Props {
  onPlanComplete: () => void
}

const POLL_MS = 1500

export function UploadPanel({ onPlanComplete }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [utility, setUtility] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [pages, setPages] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [submitting, setSubmitting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const doneRef = useRef(onPlanComplete)
  useEffect(() => {
    doneRef.current = onPlanComplete
  }, [onPlanComplete])

  const processing = plans.filter((p) => p.status === 'processing').map((p) => p.plan_id)
  const processingKey = processing.join(',')

  useEffect(() => {
    if (!processingKey) return
    const timer = setInterval(async () => {
      const updates = await Promise.all(
        processingKey.split(',').map((id) => api.plan(id).catch(() => null)),
      )
      setPlans((prev) => prev.map((p) => updates.find((u) => u?.plan_id === p.plan_id) ?? p))
      if (updates.some((u) => u && u.status !== 'processing')) doneRef.current()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [processingKey])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!file) {
      setError('Choose a PDF, XLSX, or CSV file.')
      return
    }
    setSubmitting(true)
    try {
      const ack = await api.ingest(file, utility, sourceUrl, pages)
      const plan = await api.plan(ack.plan_id)
      setPlans((prev) => [plan, ...prev])
      if (plan.status !== 'processing') onPlanComplete()
      setFile(null)
      setPages('')
      if (fileInput.current) fileInput.current.value = ''
    } catch (err) {
      if (err instanceof ApiError) {
        const detected = err.body.detected_format ? ` (detected: ${err.body.detected_format})` : ''
        setError(`${err.body.message}${detected}`)
      } else {
        setError(String(err))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="upload" aria-label="Upload a capital plan">
      <form onSubmit={submit}>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.xlsx,.csv"
          aria-label="Plan file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <input
          placeholder="Utility name"
          aria-label="Utility"
          value={utility}
          onChange={(e) => setUtility(e.target.value)}
          required
        />
        <input
          placeholder="Public source URL"
          aria-label="Source URL"
          type="url"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          required
        />
        <input
          className="pages-input"
          placeholder="Pages (all)"
          aria-label="Pages to extract"
          title="Optional. Only extract these pages, e.g. 18-45 or 3,7-9"
          value={pages}
          onChange={(e) => setPages(e.target.value)}
        />
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? 'Uploading…' : 'Ingest plan'}
        </button>
      </form>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      {plans.length ? (
        <ul className="plan-status">
          {plans.map((p) => (
            <li key={p.plan_id} className={`plan-${p.status}`}>
              <strong>{p.utility}</strong> · {p.filename}
              {p.page_range ? ` (pp. ${p.page_range})` : ''} ·{' '}
              {p.status === 'processing'
                ? 'extracting…'
                : p.status === 'complete'
                  ? `${plural(p.project_count, 'project')} extracted`
                  : `failed: ${p.error}`}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
