import type { Brief } from '../types'

// The UI is a client of the brief service. In dev, Vite proxies /api to it.

export interface Example {
  key: string
  brief_id: string
  display: string
  ai_rent_usd_per_month: number | null
}

export interface Health {
  ok: boolean
  mode: 'fixtures' | 'agent' | 'offline'
  examples: Example[]
}

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

// Generation can take a minute or two in agent mode; no client-side timeout.
export function createBrief(address: string): Promise<Brief> {
  return request<Brief>('/api/brief', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ address }),
  })
}

export function getBrief(id: string): Promise<Brief> {
  return request<Brief>(`/api/brief/${encodeURIComponent(id)}`)
}
