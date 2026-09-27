import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'

import { ApiError, UNAUTHENTICATED_EVENT, api } from '../api'

/** Who is using the app, for the top bar; null when the server has no sign-in configured. */
export interface Account {
  username: string | null
  /** Browsing without signing in: read-only, no AI features. */
  guest: boolean
  onSignOut: () => void
  /** Back to the sign-in screen (a guest choosing to sign in). */
  onSignIn: () => void
}

type Gate =
  | { status: 'checking' }
  | { status: 'open'; account: Account | null }
  | { status: 'signed-out'; expired: boolean; guests: boolean }

// A visitor who chose to browse as a guest isn't asked again on this device. Per-viewer
// convenience only: storage can be unavailable (private windows), and then they're asked.
const GUEST_KEY = 'gridmerge:guest'
function rememberGuest(on: boolean) {
  try {
    if (on) localStorage.setItem(GUEST_KEY, '1')
    else localStorage.removeItem(GUEST_KEY)
  } catch {
    /* storage unavailable */
  }
}
function wasGuest(): boolean {
  try {
    return localStorage.getItem(GUEST_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Shows the sign-in screen until the server accepts a session, or the visitor continues as a
 * guest where the server allows it. The server enforces access; this only decides what to
 * render. A 401 from the API (no session, or none for AI and edits) comes back here through
 * UNAUTHENTICATED_EVENT.
 */
export function AuthGate({ children }: { children: (account: Account | null) => ReactNode }) {
  const [gate, setGate] = useState<Gate>({ status: 'checking' })
  // Whether the server lets visitors browse as guests (from /auth/session).
  const guests = useRef(false)

  function signOut() {
    api.logout().catch(() => {
      /* the cookie is dropped server side; nothing to do if the call fails */
    })
    setGate({ status: 'signed-out', expired: false, guests: guests.current })
  }

  function signIn() {
    setGate({ status: 'signed-out', expired: false, guests: guests.current })
  }

  function open(username: string | null, required: boolean, guest = false) {
    rememberGuest(guest)
    setGate({
      status: 'open',
      account: required ? { username, guest, onSignOut: signOut, onSignIn: signIn } : null,
    })
  }

  useEffect(() => {
    api
      .session()
      .then((s) => {
        guests.current = Boolean(s.guests)
        if (!s.required || s.authenticated) open(s.username, s.required)
        else if (s.guests && wasGuest()) open(null, true, true)
        else setGate({ status: 'signed-out', expired: false, guests: Boolean(s.guests) })
      })
      // Unreachable API: render the app, which reports the connection problem itself.
      .catch(() => setGate({ status: 'open', account: null }))
    function onRejected() {
      setGate((g) =>
        g.status === 'open'
          ? { status: 'signed-out', expired: !g.account?.guest, guests: guests.current }
          : g,
      )
    }
    window.addEventListener(UNAUTHENTICATED_EVENT, onRejected)
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onRejected)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (gate.status === 'checking') return <div className="auth-screen" aria-busy="true" />
  if (gate.status === 'signed-out') {
    return (
      <SignIn
        expired={gate.expired}
        onSignedIn={(username) => open(username, true)}
        onGuest={gate.guests ? () => open(null, true, true) : undefined}
      />
    )
  }
  return <>{children(gate.account)}</>
}

function SignIn({
  expired,
  onSignedIn,
  onGuest,
}: {
  expired: boolean
  onSignedIn: (username: string | null) => void
  /** Present when the server lets visitors browse without signing in. */
  onGuest?: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = await api.login(username, password)
      onSignedIn(session.username)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.body.message : 'Could not reach GridMerge. Try again.',
      )
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-screen">
      <form className="auth-card" onSubmit={submit} aria-labelledby="auth-title">
        <div className="auth-brand">
          <img src="/favicon.svg" alt="" width={32} height={32} />
          <div>
            <h1 id="auth-title">GridMerge</h1>
            <p>Coordination radar for utility capital plans</p>
          </div>
        </div>
        {expired ? (
          <p className="auth-note" role="status">
            Your session ended. Sign in again to continue.
          </p>
        ) : null}
        <label>
          Username
          <input
            type="text"
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error ? (
          <p className="auth-error" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        {onGuest ? (
          <div className="auth-guest">
            <button type="button" className="link-button" onClick={onGuest}>
              Continue as guest
            </button>
            <p>Browse the map and opportunities. AI answers, briefs and edits need a sign-in.</p>
          </div>
        ) : null}
      </form>
    </main>
  )
}
