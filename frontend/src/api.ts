import type { BandId } from './lib/distanceBands'
import type {
  ApiErrorBody,
  AskResponse,
  CoordinationBrief,
  IngestResult,
  LineCollection,
  OverlapsResponse,
  Plan,
  Project,
  ProjectPatch,
  SearchResponse,
} from './types'

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    let body: ApiErrorBody = { code: 'http_error', message: `${res.status} ${res.statusText}` }
    try {
      const json = await res.json()
      if (json?.error) body = json.error
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, body)
  }
  return (await res.json()) as T
}

export function thresholdQuery(radius: number, bands?: BandId[]): string {
  const params = new URLSearchParams({ radius: String(radius) })
  if (bands) params.set('bands', bands.join(','))
  return params.toString()
}

export const api = {
  ingest(file: File, utility: string, sourceUrl: string, pages = ''): Promise<IngestResult> {
    const form = new FormData()
    form.append('file', file)
    form.append('utility', utility)
    form.append('source_url', sourceUrl)
    if (pages.trim()) form.append('pages', pages.trim())
    return request('/ingest', { method: 'POST', body: form })
  },
  plan: (planId: string): Promise<Plan> => request(`/plans/${encodeURIComponent(planId)}`),
  plans: (): Promise<Plan[]> => request('/plans'),
  projects: (): Promise<Project[]> => request('/projects'),
  patchProject(id: number, patch: ProjectPatch): Promise<Project> {
    return request(`/projects/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  },
  overlaps: (radius: number, bands?: BandId[]): Promise<OverlapsResponse> =>
    request(`/overlaps?${thresholdQuery(radius, bands)}`),
  brief: (pairId: string, radius: number): Promise<CoordinationBrief> =>
    request(`/overlaps/${encodeURIComponent(pairId)}/brief?${thresholdQuery(radius)}`, {
      method: 'POST',
    }),
  lines: (): Promise<LineCollection> => request('/lines'),
  /** Search bar: ZIP code, state, company, or project text (deterministic, no LLM). */
  search: (q: string, signal?: AbortSignal): Promise<SearchResponse> =>
    request(`/search?${new URLSearchParams({ q })}`, { signal }),
  /** Ask GridMerge: a Gemini answer grounded in GridMerge's own data. */
  ask: (question: string, signal?: AbortSignal): Promise<AskResponse> =>
    request('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal,
    }),
  exportUrl: (format: 'csv' | 'pdf', radius: number, bands?: BandId[]): string =>
    `${API_BASE}/export?format=${format}&${thresholdQuery(radius, bands)}`,
}
