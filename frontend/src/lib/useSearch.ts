import { useEffect, useState } from 'react'

import { api } from '../api'
import type { SearchResponse } from '../types'

const DEBOUNCE_MS = 200

/**
 * GET /search for the text in the search bar, debounced, with stale requests aborted.
 * `result` is only the answer for the current text: while a newer request is in flight
 * (or when the API is unreachable) it is null, and callers fall back to local matching.
 */
export function useSearch(query: string): { result: SearchResponse | null; loading: boolean } {
  const q = query.trim()
  const [state, setState] = useState<{ q: string; result: SearchResponse } | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!q) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => {
      setLoading(true)
      api
        .search(q, ctrl.signal)
        .then((result) => setState({ q, result }))
        .catch(() => {
          /* aborted or unreachable: local text matching still applies */
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setLoading(false)
        })
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [q])

  return { result: q && state?.q === q ? state.result : null, loading: Boolean(q) && loading }
}
