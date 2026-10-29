import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AddressInput from '../components/AddressInput'
import SignIn from '../components/SignIn'
import TestAddresses from '../components/TestAddresses'
import WhatIfPanel from '../components/WhatIfPanel'
import { ApiError, createScenario, getHealth, getPulse, streamBrief, type Health, type Me, type Pulse } from '../lib/api'
import { fmtMoney } from '../lib/format'
import { setLive, setLiveScenario, updateLive } from '../lib/live'
import { scenarioMessage } from '../lib/scenario'
import type { ScenarioInputs } from '../types'

// The five parts of a brief, in the brief page's own words. The colour on
// each tile is the kind of evidence that part usually rests on, the same key
// the brief sections and the footer use.
const PARTS = [
  { title: 'On your grid', status: 'measured', word: 'Measured', text: 'The data centers within reach of your address, with operator and distance, from PeeringDB and OpenStreetMap.' },
  { title: 'Coming', status: 'reported', word: 'Reported, checked', text: 'What is announced, permitted or under construction near you, each line cited to a page you can open.' },
  { title: 'Your bill', status: 'modelled', word: 'Modeled', text: 'Your utility’s household price over its last two reported years, from EIA-861, worked into a range for a bill like yours.' },
  { title: 'Protection', status: 'reported', word: 'Reported, checked', text: 'Whether a large-load tariff in your state shields households, and what it actually says.' },
  { title: 'Hearing', status: 'measured', word: 'Measured where indexed', text: 'What was said at the last public hearing, from the official archive, never a video platform.' },
]

export default function Home() {
  const [input, setInput] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [pulse, setPulse] = useState<Pulse | null>(null)
  const nav = useNavigate()
  const mode = health?.mode
  const live = mode === 'agent' || mode === 'full'

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ ok: false, mode: 'offline', examples: [], test_addresses: [], auth: 'off', google_client_id: null, user: null, quota_per_user_day: 0 }))
  }, [])

  // The pulse is measured and free: what PeeringDB lists, and the house-terms lines.
  useEffect(() => {
    if (!live) return
    getPulse().then(setPulse).catch(() => setPulse(null))
  }, [live])

  const onUser = useCallback((me: Me | null) => {
    setHealth((h) => (h ? { ...h, user: me } : h))
    setError(null)
  }, [])

  useEffect(() => {
    if (!busy) return
    setElapsed(0)
    const t = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(t)
  }, [busy])

  const onChange = useCallback((v: string) => { setInput(v); setError(null) }, [])

  // The what-if is the engine's arithmetic: no sign-in, no model, so a spinner
  // is all the waiting it needs. The page opens from the result, no refetch.
  const [whatIfBusy, setWhatIfBusy] = useState(false)
  const [whatIfError, setWhatIfError] = useState<string | null>(null)
  async function dropIt(inputs: ScenarioInputs) {
    if (whatIfBusy) return
    setWhatIfError(null)
    setWhatIfBusy(true)
    try {
      const s = await createScenario(inputs)
      setLiveScenario(s.scenario_id, s)
      nav(`/what-if/${s.scenario_id}`)
    } catch (err) {
      setWhatIfError(scenarioMessage(err))
      setWhatIfBusy(false)
    }
  }

  async function go(e: React.FormEvent) {
    e.preventDefault()
    if (busy || !input.trim()) return
    setError(null)
    setBusy(true)
    // The brief streams in stages. The first partial (the facts: map, utility,
    // bill number) moves us to the brief page; later events update it there.
    let id: string | null = null
    const startedAt = Date.now()
    try {
      await streamBrief(input, (ev) => {
        if (ev.stage === 'error') return // thrown by streamBrief instead
        if (ev.stage === 'verifying') {
          if (id) updateLive(id, { stage: 'verifying', verified: ev.verified, claims: ev.claims })
          return
        }
        const first = id === null
        const bid = ev.brief.brief_id
        id = bid
        setLive(bid, { brief: ev.brief, stage: ev.stage, verified: 0, claims: 0, startedAt, endedAt: ev.stage === 'done' ? Date.now() : undefined })
        if (first) nav(`/b/${bid}`)
      })
    } catch (err) {
      if (id) updateLive(id, { stage: 'error', error: messageFor(err, mode) })
      else setError(messageFor(err, mode))
      // A spent quota shows up in the count; a lost session shows the button again.
      if (err instanceof ApiError && (err.status === 401 || err.status === 429)) {
        getHealth().then(setHealth).catch(() => undefined)
      }
    } finally {
      setBusy(false)
    }
  }

  const gated = health?.auth === 'google'
  const signedIn = Boolean(health?.user)

  return (
    <main className="mx-auto max-w-5xl px-4">
      <header className="flex min-h-14 items-center justify-between gap-4 py-3">
        <span className="wide inline-flex items-center gap-2 text-sm font-semibold">
          <svg viewBox="0 0 32 32" aria-hidden="true" className="h-6 w-6">
            <rect width="32" height="32" fill="var(--ink)" />
            <path d="M18 4 8 18h7l-1 10 10-14h-7z" fill="var(--signal)" />
          </svg>
          Who's on my grid
          <span aria-hidden className="mx-1 h-5 w-px bg-[var(--line)]" />
          <a
            href="https://www.ecoprism.com"
            rel="noopener"
            className="inline-flex items-center gap-1.5 font-normal text-[var(--ink-soft)] no-underline hover:text-[var(--ink)]"
          >
            by <img src="/ecoprism.png" alt="EcoPrism" className="h-5 w-auto" />
          </a>
        </span>
        {health && <SignIn health={health} onUser={onUser} />}
      </header>

      <section className="pt-8 sm:pt-12">
        <h1 className="sign text-[clamp(3rem,9vw,6.5rem)]">
          Who's on<br />my grid?
        </h1>
        <p className="mt-6 max-w-[60ch] text-xl leading-snug">
          Which data centers are on your local grid, what is being built near you, what your bill has
          done and when the next vote is. Or drop a hypothetical one on your town and see what it would take.
        </p>
      </section>

      {/* Two doors side by side from lg up: a real address (a checked brief), or a ZIP (a modelled what-if). */}
      <div className="mt-10 grid items-start gap-x-12 gap-y-14 lg:grid-cols-2">
        <section aria-labelledby="door-address" className="border-t-4 border-[var(--signal)] pt-5">
          <h2 id="door-address" className="text-2xl font-bold leading-none">Check your address</h2>
          <p className="mt-3 max-w-[56ch] text-[var(--ink-soft)]">
            A street address in, a brief out: the data centers on your grid, your bill, your tariff and
            the last hearing. Every sentence cites a page you can open.
          </p>
          <form onSubmit={go} className="mt-6">
            <label htmlFor="address" className="block text-sm text-[var(--ink-soft)]">
              Street address, city, state
            </label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <AddressInput value={input} onChange={onChange} disabled={busy} />
              <button type="submit" disabled={busy} className="btn-signal shrink-0 px-6 py-3 text-lg">
                {busy ? 'Working…' : 'Check my grid'}
              </button>
            </div>
            {live && <TestAddresses items={health?.test_addresses} onPick={onChange} disabled={busy} />}
            {gated && !busy && (
              <p className="mt-3 text-sm text-[var(--ink-soft)]">
                {signedIn
                  ? 'A new address spends model time, so each person gets a few a day. Test addresses and shared briefs are always free.'
                  : 'Test addresses and shared briefs run without an account. A new address needs a Google sign-in, because each one spends model time.'}
              </p>
            )}
            {busy && live && (
              <p className="mt-3 text-sm text-[var(--ink-soft)]" aria-live="polite">
                Spark is drafting five sections, then Spark Open fetches every cited page and checks each
                claim. Usually 30–90 seconds. <span className="num">{elapsed}s</span>
              </p>
            )}
            {error && (
              <p className="mt-3 text-sm" role="alert">{error}</p>
            )}
          </form>
        </section>

        {mode !== 'offline' && (
          <section className="border-t-4 border-[var(--modelled)] pt-5">
            <WhatIfPanel onSubmit={dropIt} busy={whatIfBusy} error={whatIfError} />
          </section>
        )}
      </div>

      {mode === 'fixtures' && health && (
        <section className="mt-14 max-w-3xl">
          <h2 className="text-sm text-[var(--ink-soft)]">Example addresses</h2>
          <ul className="mt-3 divide-y divide-[var(--line)] border-y border-[var(--line)]">
            {health.examples.map((ex) => (
              <li key={ex.key}>
                <a href={`/b/${ex.key}`} className="flex items-baseline justify-between gap-4 py-3 no-underline hover:bg-white">
                  <span className="font-semibold">{ex.display}</span>
                  <span className="num shrink-0 text-sm text-[var(--ink-soft)]">
                    {ex.ai_rent_usd_per_month === null ? 'bill: not known' : `about ${fmtMoney(ex.ai_rent_usd_per_month)}/mo`}
                  </span>
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm text-[var(--ink-soft)]">
            Every operator, source and quote in these examples is fictional. They exist to build the page against.
          </p>
        </section>
      )}

      {pulse && (pulse.peeringdb || pulse.equivalences.length > 0) && (
        <section className="mt-20 border-t-4 border-[var(--measured)] pt-5">
          <h2 className="tag-measured text-sm font-semibold">Measured today</h2>
          <div className="mt-4 grid gap-x-12 gap-y-10 md:grid-cols-[1fr_1.3fr]">
            {pulse.peeringdb && (
              <div>
                <p className="wide num text-[clamp(3.2rem,8vw,5.6rem)] font-bold leading-none tracking-tight">
                  {pulse.peeringdb.total.toLocaleString('en-US')}
                </p>
                <p className="mt-3 max-w-[32ch] text-lg leading-snug">
                  data-center facilities in the United States, as{' '}
                  <a href={pulse.peeringdb.source_url} rel="noopener">{pulse.peeringdb.source_title}</a> lists them today
                  {pulse.peeringdb.added !== null && (
                    <>
                      . <span className="num font-semibold">{pulse.peeringdb.added.toLocaleString('en-US')}</span>{' '}
                      {pulse.peeringdb.added === 1 ? 'was' : 'were'} added in the last {pulse.peeringdb.days} days
                    </>
                  )}
                  .
                </p>
              </div>
            )}
            {pulse.equivalences.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold leading-tight">A data center, in house terms</h3>
                <ul className="mt-3 divide-y divide-[var(--line)] border-y border-[var(--line)]">
                  {pulse.equivalences.map((e) => (
                    <li key={e.id} className="py-3">
                      <p className="leading-snug">{e.text}</p>
                      <p className="mt-1 text-sm text-[var(--ink-soft)]">
                        {e.basis} Source: <a href={e.source_url} rel="noopener" title={e.quote}>{e.source_title}</a>.
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      {live && (
        <section className="mt-20">
          <h2 className="text-2xl font-bold leading-none">What comes back</h2>
          <p className="mt-3 max-w-[60ch] text-[var(--ink-soft)]">
            One brief in five parts, on a map of your grid. The colour on each part is the kind of
            evidence behind it, and a part that does not know says so.
          </p>
          <ul className="mt-8 grid gap-x-6 gap-y-8 sm:grid-cols-2 lg:grid-cols-5">
            {PARTS.map((p) => (
              <li key={p.title} className={`tile tile-${p.status} pt-3`}>
                <h3 className="text-xl font-bold leading-tight">{p.title}</h3>
                <p className={`tag-${p.status} mt-1 text-xs font-semibold`}>{p.word}</p>
                <p className="mt-2 text-sm leading-snug text-[var(--ink-soft)]">{p.text}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mode === 'agent' && (
        <p className="mt-14 max-w-[64ch] text-sm text-[var(--ink-soft)]">
          Any US street address. Operators, sources and quotes come from Muse Spark's own knowledge
          and are checked against the cited pages by Muse Spark Open. Nothing is verified against
          ground-truth data yet, and the brief says so on every section.
        </p>
      )}

      {mode === 'offline' && (
        <p className="mt-14 text-sm" role="alert">
          The brief service is not running. Start it with <code>uv run uvicorn app.main:create_app --factory</code> in services/api.
        </p>
      )}
    </main>
  )
}

function messageFor(err: unknown, mode: Health['mode'] | undefined): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 404:
        return mode === 'fixtures'
          ? 'Only the five example addresses below work while the app runs on fixtures. Pick one of them.'
          : 'No brief for that address.'
      case 422:
        return 'Could not find that US address. Include the street number, city and state.'
      case 403:
        return err.detail === 'cross_site'
          ? 'That request did not come from this page. Reload and try again.'
          : 'This service covers US addresses and is only available from the United States.'
      case 401:
        return 'Sign in with Google at the top of the page to run a new address. Test addresses and shared briefs need no sign-in.'
      case 429:
        return err.detail === 'quota_exceeded_user'
          ? "You have used today's new briefs. Try again tomorrow, or open a shared brief."
          : "Today's brief budget is spent. Shared briefs and the test addresses still open."
      case 503:
        return 'The address lookup service is not answering. Try again in a minute.'
      case 502:
        return 'The drafting model did not answer. Try again.'
      default:
        return `Something went wrong (${err.status}).`
    }
  }
  return 'Cannot reach the brief service. Is it running?'
}
