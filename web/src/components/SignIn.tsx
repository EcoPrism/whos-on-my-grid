import { useEffect, useRef, useState } from 'react'
import { signInWithGoogle, signOut, type Health, type Me } from '../lib/api'

// Google Identity Services. The script is loaded once, on demand, only when
// the service says sign-in is Google's. The id_token goes to our API, which
// sets an HttpOnly cookie; nothing is kept in JavaScript.

type GisButtonOptions = { theme: string; size: string; text: string; shape: string; width?: number }
type Gis = {
  accounts: {
    id: {
      initialize(opts: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }): void
      renderButton(el: HTMLElement, opts: GisButtonOptions): void
      disableAutoSelect(): void
    }
  }
}
// window.google is shared with the Maps loader in AddressInput; read it loosely.
function gis(): Gis | undefined {
  const g = (window as unknown as { google?: Partial<Gis> }).google
  return g?.accounts?.id ? (g as Gis) : undefined
}

let loading: Promise<Gis> | null = null
function loadGis(): Promise<Gis> {
  const ready = gis()
  if (ready) return Promise.resolve(ready)
  if (loading) return loading
  loading = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.defer = true
    s.onload = () => {
      const g = gis()
      if (g) resolve(g)
      else reject(new Error('gis'))
    }
    s.onerror = () => reject(new Error('gis'))
    document.head.appendChild(s)
  })
  return loading
}

export default function SignIn({ health, onUser }: { health: Health; onUser: (me: Me | null) => void }) {
  const slot = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const clientId = health.google_client_id
  const user = health.user

  useEffect(() => {
    if (user || !clientId || !slot.current) return
    let cancelled = false
    const el = slot.current
    loadGis()
      .then((g) => {
        if (cancelled) return
        g.accounts.id.initialize({
          client_id: clientId,
          ux_mode: 'popup',
          callback: async ({ credential }) => {
            setBusy(true)
            setError(null)
            try {
              onUser(await signInWithGoogle(credential))
            } catch {
              setError('Sign-in did not go through. Try again.')
            } finally {
              setBusy(false)
            }
          },
        })
        g.accounts.id.renderButton(el, { theme: 'outline', size: 'large', text: 'signin_with', shape: 'rectangular' })
      })
      .catch(() => setError('Could not load Google sign-in.'))
    return () => {
      cancelled = true
    }
  }, [user, clientId, onUser])

  if (health.auth !== 'google') return null

  if (user) {
    return (
      <p className="mt-3 text-sm text-[var(--ink-soft)]">
        Signed in as <span className="text-[var(--ink)]">{user.email}</span>.{' '}
        <span className="num">{user.remaining}</span> of {health.quota_per_user_day} new briefs left today.{' '}
        <button
          type="button"
          className="underline underline-offset-[3px]"
          onClick={async () => {
            await signOut().catch(() => undefined)
            gis()?.accounts.id.disableAutoSelect()
            onUser(null)
          }}
        >
          Sign out
        </button>
      </p>
    )
  }

  return (
    <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
      <div ref={slot} aria-busy={busy} className="min-h-10" />
      <p className="text-sm text-[var(--ink-soft)]">
        Sign in to run a new address. Shared briefs and the example addresses need no sign-in.
      </p>
      {error && <p className="text-sm" role="alert">{error}</p>}
    </div>
  )
}
