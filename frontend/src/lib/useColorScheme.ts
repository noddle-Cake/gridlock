import { useEffect, useState } from 'react'

const QUERY = '(prefers-color-scheme: dark)'

/** The OS colour scheme, tracked live. */
export function useColorScheme(): 'light' | 'dark' {
  const [dark, setDark] = useState(() => window.matchMedia?.(QUERY).matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY)
    if (!mq) return
    const on = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return dark ? 'dark' : 'light'
}
