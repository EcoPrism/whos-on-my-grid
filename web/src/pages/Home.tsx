import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AddressInput from '../components/AddressInput'
import TestAddresses from '../components/TestAddresses'
import { ApiError, getHealth, streamBrief, type Health } from '../lib/api'
import { setLive, updateLive } from '../lib/live'

export default function Home() {
  const [input, setInput] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const nav = useNavigate()
  const mode = health?.mode

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ ok: false, mode: 'offline', examples: [] }))
  }, [])

  useEffect(() => {
    if (!busy) return
    setElapsed(0)
    const t = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(t)
  }, [busy])

  const onChange = useCallback((v: string) => { setInput(v); setError(null) }, [])

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
        setLive(bid, { brief: ev.brief, stage: ev.stage, verified: 0, claims: 0, startedAt })
        if (first) nav(`/b/${bid}`)
      })
    } catch (err) {
      if (id) updateLive(id, { stage: 'error', error: messageFor(err, mode) })
      else setError(messageFor(err, mode))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-14 sm:pt-24">
      <h1 className="sign text-[clamp(3.2rem,12vw,7.5rem)]">
        Who's on<br />my grid?
      </h1>
      <p className="mt-8 max-w-[52ch] text-xl leading-snug">
        Type a US address. Find out which data centers are on your local grid, what is being built
        near you, what your bill has done, and when the next vote is.
      </p>

      <form onSubmit={go} className="mt-10">
        <label htmlFor="address" className="block text-sm text-[var(--ink-soft)]">
          Street address, city, state
        </label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <AddressInput value={input} onChange={onChange} disabled={busy} />
          <button
            type="submit"
            disabled={busy}
            className="shrink-0 border-2 border-[var(--ink)] bg-[var(--ink)] px-6 py-3 text-lg font-semibold text-[var(--paper)] disabled:opacity-60"
          >
            {busy ? 'Working…' : 'Check my grid'}
          </button>
        </div>
        {(mode === 'agent' || mode === 'full') && (
          <TestAddresses onPick={onChange} disabled={busy} />
        )}
        {busy && (mode === 'agent' || mode === 'full') && (
          <p className="mt-3 text-sm text-[var(--ink-soft)]" aria-live="polite">
            Spark is drafting five sections, then Spark Open fetches every cited page and checks each
            claim. Usually 30–90 seconds. <span className="num">{elapsed}s</span>
          </p>
        )}
        {error && (
          <p className="mt-3 text-sm" role="alert">{error}</p>
        )}
      </form>

      {mode === 'fixtures' && health && (
        <section className="mt-14">
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
        return 'This service covers US addresses and is only available from the United States.'
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

export function fmtMoney(n: number) {
  const sign = n < 0 ? '−' : '+'
  return `${sign}$${Math.abs(n).toFixed(0)}`
}

// The modeled bill change is shown as a range, never as a point estimate alone.
export function fmtRange([lo, hi]: [number, number]) {
  const sign = hi < 0 ? '−' : '+'
  return `${sign}$${Math.abs(lo).toFixed(0)} to $${Math.abs(hi).toFixed(0)}`
}
