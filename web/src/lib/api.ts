import type { Brief, CardInfo } from '../types'

// The UI is a client of the brief service. In dev, Vite proxies /api to it.

export interface Example {
  key: string
  brief_id: string
  display: string
  ai_rent_usd_per_month: number | null
}

// Who is signed in, and how many new briefs they have left today.
export interface Me {
  email: string
  remaining: number
}

export interface Health {
  ok: boolean
  mode: 'fixtures' | 'agent' | 'full' | 'offline'
  examples: Example[]
  // Addresses that run without a sign-in (the test set), as the API spells them.
  test_addresses: string[]
  // off: anyone can generate (local dev). google: new briefs need a Google sign-in.
  auth: 'off' | 'google' | 'fake'
  google_client_id: string | null
  user: Me | null
  quota_per_user_day: number
}

export interface PulsePeeringDB {
  total: number
  added: number | null
  days: number
  source_url: string
  source_title: string
}

export interface Equivalence {
  id: string
  text: string
  basis: string
  source_url: string
  source_title: string
  quote: string
}

export interface Pulse {
  peeringdb: PulsePeeringDB | null
  equivalences: Equivalence[]
}

// Every POST carries this header: with SameSite cookies it is the second belt
// against a cross-site form spending a signed-in user's quota.
const POST_HEADERS = { 'content-type': 'application/json', 'x-requested-with': 'grid' }

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* no JSON body */
    }
    throw new ApiError(r.status, String(detail))
  }
  return r.json() as Promise<T>
}

export function getHealth(): Promise<Health> {
  return request<Health>('/api/health')
}

export function getPulse(): Promise<Pulse> {
  return request<Pulse>('/api/pulse')
}

export function signInWithGoogle(credential: string): Promise<Me> {
  return request<Me>('/api/auth/google', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify({ credential }),
  })
}

export function signOut(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/api/auth/logout', { method: 'POST', headers: POST_HEADERS })
}

// Generation can take a minute or two in agent mode; no client-side timeout.
export function createBrief(address: string): Promise<Brief> {
  return request<Brief>('/api/brief', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify({ address }),
  })
}

// One event per line from /api/brief/stream while the brief is made.
export type BriefEvent =
  | { stage: 'ground' | 'drafting' | 'done'; brief: Brief }
  | { stage: 'verifying'; verified: number; claims: number }
  | { stage: 'error'; status: number; detail: string }

// The streaming twin of createBrief: `onEvent` sees the brief take shape, the
// promise resolves with the finished brief. Errors reported on the stream
// become ApiErrors like the plain endpoint's.
export async function streamBrief(address: string, onEvent: (ev: BriefEvent) => void): Promise<Brief> {
  const r = await fetch('/api/brief/stream', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify({ address }),
  })
  if (!r.ok || !r.body) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* no JSON body */
    }
    throw new ApiError(r.status, String(detail))
  }
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: Brief | null = null
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl = buffer.indexOf('\n')
    while (nl >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      nl = buffer.indexOf('\n')
      if (!line) continue
      const ev = JSON.parse(line) as BriefEvent
      if (ev.stage === 'error') throw new ApiError(ev.status, ev.detail)
      onEvent(ev)
      if (ev.stage === 'done') final = ev.brief
    }
  }
  if (!final) throw new ApiError(0, 'The brief stream ended before the brief was finished.')
  return final
}

export function getBrief(id: string): Promise<Brief> {
  return request<Brief>(`/api/brief/${encodeURIComponent(id)}`)
}

// The share card's text and absolute URLs, for a brief or a what-if scenario.
export function getCard(kind: CardInfo['kind'], id: string): Promise<CardInfo> {
  const base = kind === 'brief' ? '/api/card' : '/api/scenario-card'
  return request<CardInfo>(`${base}/${encodeURIComponent(id)}.json`)
}
