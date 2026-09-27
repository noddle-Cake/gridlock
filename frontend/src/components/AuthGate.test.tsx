import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { UNAUTHENTICATED_EVENT } from '../api'
import { AuthGate } from './AuthGate'

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

const signedOut = { required: true, authenticated: false, username: null }
const signedIn = { required: true, authenticated: true, username: 'planner@example.com' }

describe('AuthGate', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/auth/session') return json(signedOut)
      if (url === '/api/auth/logout') return json(signedOut)
      if (url === '/api/auth/login') {
        const { username, password } = JSON.parse(String(init?.body))
        return password === 'right'
          ? json({ ...signedIn, username })
          : json({ error: { code: 'invalid_credentials', message: 'Wrong username or password.' } }, 401)
      }
      return Promise.reject(new Error(`unexpected ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  function renderGate() {
    render(
      <AuthGate>
        {(account) => (
          <div>
            <p>the app</p>
            {account ? (
              <button type="button" onClick={account.onSignOut}>
                Sign out {account.username}
              </button>
            ) : null}
          </div>
        )}
      </AuthGate>,
    )
  }

  it('asks for credentials, then shows the app', async () => {
    renderGate()
    await userEvent.type(await screen.findByLabelText('Username'), 'planner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'right{Enter}')
    expect(await screen.findByText('the app')).toBeInTheDocument()
    const login = fetchMock.mock.calls.find((c) => c[0] === '/api/auth/login')!
    expect(JSON.parse(String(login[1].body))).toEqual({
      username: 'planner@example.com',
      password: 'right',
    })
    expect(login[1].credentials).toBe('include')
  })

  it('shows the server message on a wrong password and clears the field', async () => {
    renderGate()
    await userEvent.type(await screen.findByLabelText('Username'), 'planner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.queryByText('the app')).toBeNull()
  })

  it('opens straight away when the session is valid or sign-in is off', async () => {
    fetchMock.mockImplementationOnce(() => json(signedIn))
    renderGate()
    expect(await screen.findByRole('button', { name: 'Sign out planner@example.com' }))
      .toBeInTheDocument()
  })

  it('has no sign-out when the server has no sign-in configured', async () => {
    fetchMock.mockImplementationOnce(() => json({ required: false, authenticated: true, username: null }))
    renderGate()
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Sign out/ })).toBeNull()
  })

  it('returns to sign-in when the session expires or the user signs out', async () => {
    fetchMock.mockImplementationOnce(() => json(signedIn))
    renderGate()
    await screen.findByText('the app')
    act(() => {
      window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT))
    })
    expect(await screen.findByText(/Your session ended/)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Username'), 'planner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'right{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: /Sign out/ }))
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.queryByText(/Your session ended/)).toBeNull()
    expect(fetchMock.mock.calls.some((c) => c[0] === '/api/auth/logout')).toBe(true)
  })
})
