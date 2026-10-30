import type { Brief, CardInfo, Locale, Scenario, ScenarioInputs } from '../types'

// The UI is a client of the brief service. In dev, Vite proxies /api to it.

export interface Example {
  key: string
  brief_id: string
  display: string
  // In `currency` (the key name is the legacy one).
  ai_rent_usd_per_month: number | null
  currency?: string
  language?: string
}

// One region this deployment serves (/api/health `regions[]`). Every field past
// id and label is optional so an older API still reads as the US.
export interface RegionInfo {
  id: string
  label: string
  countries?: string[]
  // Countries the Places autocomplete is restricted to (lower case).
  places_country?: string[]
  locale?: Locale
  // Whether the what-if runs for this region.
  scenarios?: boolean
  placeholder?: string
  address_label?: string
  // Shown on a brief whose address this region's geocoder found.
  geocoder_attribution?: string | null
  // The footer's data line.
  sources_line?: string
  // 0: briefs are kept; otherwise they are deleted that many days after they are made.
  brief_ttl_days?: number
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
  // Addresses that cost no quota (the test set), as the API spells them.
  test_addresses: string[]
  // off: anyone can generate (local dev). google: every address check needs a Google sign-in.
  auth: 'off' | 'google' | 'fake'
  google_client_id: string | null
  user: Me | null
  quota_per_user_day: number
  // The region new briefs are made for, and the ones this deployment serves.
  region?: string
  regions?: RegionInfo[]
  // The requested region's settings, repeated at the top level.
  locale?: Locale
  scenarios?: boolean
  places_country?: string[]
  brief_ttl_days?: number
}

export interface PulsePeeringDB {
  total: number
  added: number | null
  days: number
  source_url: string
  source_title: string
  // The countries counted, e.g. ["IE"]; absent on an older API (the US).
  countries?: string[]
}

export interface Equivalence {
  id: string
  text: string
  basis: string
  source_url: string
  source_title: string
  quote: string
}

// One cited constant, as /api/pulse sends it (app/pulse.py cited_constants).
export interface PulseConstant {
  value: number
  unit: string
  as_of: string
  source_url: string
  source_title: string
  quote: string
}

// What a campus's MW means: a size tier or one of the largest AI campuses
// announced (data/equivalences.json "scale"). Reported, not measured.
export interface ScaleRef {
  id: string
  mw: number
  kind: 'typical' | 'frontier'
  name: string
  size: string
  // How mw reads: at most (a tier's top), more than (a tier's floor), or a campus's own size.
  bound: 'up_to' | 'over' | 'about'
  // What that size looks like, in plain words, restating detail_quote from the same page.
  detail: string
  detail_quote: string
  source_title: string
  source_url: string
  quote: string
  checked: string
}

export interface Pulse {
  peeringdb: PulsePeeringDB | null
  equivalences: Equivalence[]
  // The scenario engine's cited constants, keyed by id. Absent in fixtures mode.
  constants?: Record<string, PulseConstant>
  // Smallest first.
  scale?: ScaleRef[]
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

async function errorOf(r: Response): Promise<ApiError> {
  let detail = r.statusText
  try {
    detail = (await r.json()).detail ?? detail
  } catch {
    /* no JSON body */
  }
  return new ApiError(r.status, String(detail))
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) throw await errorOf(r)
  return r.json() as Promise<T>
}

// With no region the API picks one (the country header, then its default)
// and says which in `region`.
export function getHealth(region?: string): Promise<Health> {
  return request<Health>(region ? `/api/health?region=${encodeURIComponent(region)}` : '/api/health')
}

// The API's answer when a region id is not one it serves.
export function isUnknownRegion(e: unknown): boolean {
  return e instanceof ApiError && e.status === 422 && e.detail === 'unknown_region'
}

// One request per region per page load, shared by every caller (the home
// page's pulse strip and the MW slider's homes label). A failure lets a later
// call retry. The region defaults to 'us' because the what-if, which is
// US-only, calls this bare (MwSlider, Interpretation) and needs US constants.
const pulses = new Map<string, Promise<Pulse>>()
export function getPulse(region = 'us'): Promise<Pulse> {
  let p = pulses.get(region)
  if (!p) {
    p = request<Pulse>(`/api/pulse?region=${encodeURIComponent(region)}`).catch((e: unknown) => {
      pulses.delete(region)
      throw e
    })
    pulses.set(region, p)
  }
  return p
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
// No region lets the API pick, as for health.
export function createBrief(address: string, region?: string): Promise<Brief> {
  return request<Brief>('/api/brief', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify(region ? { address, region } : { address }),
  })
}

// One event per line from /api/brief/stream while the brief is made.
export type GroundStep = 'facilities' | 'utility' | 'prices' | 'tariff' | 'imagery' | 'hearings'
export type StepState = 'ok' | 'none' | 'failed'
export type BriefEvent =
  | { stage: 'gathering'; step: GroundStep; state: StepState }
  | { stage: 'ground' | 'drafting' | 'done'; brief: Brief }
  | { stage: 'verifying'; verified: number; claims: number }
  | { stage: 'error'; status: number; detail: string }

// Reads a newline-delimited JSON response, calling `onLine` with each parsed
// line as it arrives. A non-OK response becomes an ApiError like request()'s.
export async function readNdjson<T>(r: Response, onLine: (line: T) => void): Promise<void> {
  if (!r.ok || !r.body) throw await errorOf(r)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
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
      onLine(JSON.parse(line) as T)
    }
  }
}

// The streaming twin of createBrief: `onEvent` sees the brief take shape, the
// promise resolves with the finished brief. Errors reported on the stream
// become ApiErrors like the plain endpoint's.
export async function streamBrief(address: string, region: string | undefined, onEvent: (ev: BriefEvent) => void): Promise<Brief> {
  const r = await fetch('/api/brief/stream', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify(region ? { address, region } : { address }),
  })
  let final = null as Brief | null
  await readNdjson<BriefEvent>(r, (ev) => {
    if (ev.stage === 'error') throw new ApiError(ev.status, ev.detail)
    onEvent(ev)
    if (ev.stage === 'done') final = ev.brief
  })
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

// A what-if: the engine's arithmetic for a hypothetical campus. No sign-in,
// no model, so it comes back in about a second once the area is cached.
export function createScenario(inputs: ScenarioInputs): Promise<Scenario> {
  return request<Scenario>('/api/scenario', {
    method: 'POST',
    headers: POST_HEADERS,
    body: JSON.stringify(inputs),
  })
}

export function getScenario(id: string): Promise<Scenario> {
  return request<Scenario>(`/api/scenario/${encodeURIComponent(id)}`)
}

// One event per line from /api/scenario/{id}/interpret while Muse Spark
// drafts the plain-words paragraph and the verifier checks its claims. A
// failure partway is a final error line; one before the stream starts is an
// HTTP error (401 sign-in, 429 quota, 404, 503).
export type InterpretEvent =
  | { stage: 'drafting' }
  | { stage: 'verifying'; verified: number; claims: number }
  | { stage: 'done'; scenario: Scenario }
  | { stage: 'error'; status?: number; detail: string }

// Needs a sign-in and spends one of the user's daily model runs, charged once
// per scenario; an explanation already made comes back as `done` at once.
// Resolves with the scenario carrying its `interpretation`.
export async function streamInterpretation(id: string, onEvent: (ev: InterpretEvent) => void): Promise<Scenario> {
  const r = await fetch(`/api/scenario/${encodeURIComponent(id)}/interpret`, {
    method: 'POST',
    headers: POST_HEADERS,
    credentials: 'same-origin',
  })
  let final = null as Scenario | null
  await readNdjson<InterpretEvent>(r, (ev) => {
    if (ev.stage === 'error') throw new ApiError(ev.status ?? statusOfDetail(ev.detail), ev.detail)
    onEvent(ev)
    if (ev.stage === 'done') final = ev.scenario
  })
  if (!final) throw new ApiError(0, 'The explanation stream ended before it was finished.')
  return final
}

// An error line may carry only the detail; give it the status the same
// failure has as an HTTP error, so the page words both alike.
function statusOfDetail(detail: string): number {
  if (detail === 'sign_in_required') return 401
  if (detail.startsWith('quota_exceeded')) return 429
  if (detail === 'not_found') return 404
  if (detail === 'interpretation_unavailable') return 503
  return 502
}
