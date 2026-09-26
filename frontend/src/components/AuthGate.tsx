import { type FormEvent, type ReactNode, useEffect, useState } from 'react'

import { ApiError, UNAUTHENTICATED_EVENT, api } from '../api'

/** Who is signed in, for the top bar; null when the server has no sign-in configured. */
export interface Account {
  username: string | null
  onSignOut: () => void
}

type Gate =
  | { status: 'checking' }
  | { status: 'open'; account: Account | null }
  | { status: 'signed-out'; expired: boolean }

/**
 * Shows the sign-in screen until the server accepts a session. The server enforces access;
 * this only decides what to render. Any 401 from the API (an expired session) comes back
 * here through UNAUTHENTICATED_EVENT.
 */
export function AuthGate({ children }: { children: (account: Account | null) => ReactNode }) {
  const [gate, setGate] = useState<Gate>({ status: 'checking' })

  function signOut() {
    api.logout().catch(() => {
      /* the cookie is dropped server side; nothing to do if the call fails */
    })
    setGate({ status: 'signed-out', expired: false })
  }

  function open(username: string | null, required: boolean) {
    setGate({ status: 'open', account: required ? { username, onSignOut: signOut } : null })
  }

  useEffect(() => {
    api
      .session()
      .then((s) =>
        s.required && !s.authenticated
          ? setGate({ status: 'signed-out', expired: false })
          : open(s.username, s.required),
      )
      // Unreachable API: render the app, which reports the connection problem itself.
      .catch(() => setGate({ status: 'open', account: null }))
    function onExpired() {
      setGate((g) => (g.status === 'open' ? { status: 'signed-out', expired: true } : g))
    }
    window.addEventListener(UNAUTHENTICATED_EVENT, onExpired)
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onExpired)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (gate.status === 'checking') return <div className="auth-screen" aria-busy="true" />
  if (gate.status === 'signed-out') {
    return <SignIn expired={gate.expired} onSignedIn={(username) => open(username, true)} />
  }
  return <>{children(gate.account)}</>
}

function SignIn({
  expired,
  onSignedIn,
}: {
  expired: boolean
  onSignedIn: (username: string | null) => void
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
      </form>
    </main>
  )
}
