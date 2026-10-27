import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Claims from '../components/Claims'
import MapView from '../components/MapView'
import { SECTION_TITLES, SectionBlock } from '../components/Sections'
import ShareCard from '../components/ShareCard'
import { ApiError, getBrief } from '../lib/api'
import type { Brief, SectionId, Status } from '../types'
import { fmtMoney } from './Home'

const ORDER: SectionId[] = ['on_your_grid', 'coming', 'your_bill', 'protection', 'hearing']

const STATUS_WORD: Record<Status, string> = {
  measured: 'Measured',
  reported: 'Reported',
  modelled: 'Modelled',
  unavailable: 'Not known',
}

type State = { kind: 'loading' } | { kind: 'missing' } | { kind: 'error'; message: string } | { kind: 'ready'; brief: Brief }

// One screen: the map with the headline on it, five tiles, and the detail
// for whichever tile is open. Everything else folds away.
export default function BriefPage() {
  const { key = '' } = useParams()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [open, setOpen] = useState<SectionId | null>(null)

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    setOpen(null)
    getBrief(key)
      .then((brief) => { if (!cancelled) setState({ kind: 'ready', brief }) })
      .catch((err: unknown) => { if (!cancelled) setState(stateForError(err)) })
    return () => { cancelled = true }
  }, [key])

  if (state.kind === 'loading') {
    return (
      <main className="mx-auto max-w-3xl px-4 py-24">
        <p className="text-[var(--ink-soft)]">Loading the brief…</p>
      </main>
    )
  }
  if (state.kind === 'missing') {
    return (
      <main className="mx-auto max-w-3xl px-4 py-24">
        <h1 className="sign text-5xl">No brief for that address</h1>
        <p className="mt-6">Briefs are kept by a hash of the address. <Link to="/">Type the address again to generate one.</Link></p>
      </main>
    )
  }
  if (state.kind === 'error') {
    return (
      <main className="mx-auto max-w-3xl px-4 py-24">
        <h1 className="sign text-5xl">Could not load the brief</h1>
        <p className="mt-6" role="alert">{state.message} <Link to="/">Back to the address box.</Link></p>
      </main>
    )
  }

  const brief = state.brief
  const a = brief.address
  const h = brief.headline
  const supported = brief.claims.filter((c) => c.verdict === 'supported').length

  return (
    <main className="pb-16">
      <nav className="mx-auto flex max-w-6xl items-baseline justify-between px-4 pt-4 text-sm">
        <Link to="/" className="no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
        {brief.fixture && <span className="text-[var(--ink-soft)]">Fixture. Operators and sources are fictional.</span>}
        {brief.source_mode === 'agent' && <span className="text-[var(--ink-soft)]">Drafted by Muse Spark from its own knowledge. Checked, not measured.</span>}
      </nav>

      {/* Hero: the map, with the headline card on top of it. */}
      <div className="relative mx-auto mt-3 max-w-6xl sm:px-4">
        <MapView brief={brief} className="h-[52vh] min-h-[380px] w-full sm:h-[62vh]" />
        <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3 sm:left-4 sm:right-auto sm:max-w-md sm:p-5">
          <div className="pointer-events-auto border-2 border-[var(--ink)] bg-[var(--paper)]/95 p-4 shadow-[6px_6px_0_var(--ink)] backdrop-blur-sm">
            <p className="text-sm text-[var(--ink-soft)]">{a.county ? `${a.county} County, ` : ''}{a.state}{a.utility ? ` · served by ${a.utility}` : ''}</p>
            <h1 className="sign mt-1 text-[clamp(1.9rem,5vw,3rem)]">{a.display}</h1>
            <div className="mt-3 flex items-end justify-between gap-4">
              {h.one_liner && <p className="max-w-[34ch] text-[15px] leading-snug">{h.one_liner}</p>}
              {h.ai_rent_usd_per_month !== null && (
                <p className="num shrink-0 text-right">
                  <span className="block text-4xl font-extrabold leading-none text-[var(--signal)] [text-shadow:0_0_0_var(--ink),1px_1px_0_var(--ink)]">{fmtMoney(h.ai_rent_usd_per_month)}</span>
                  <span className="block text-xs text-[var(--ink-soft)]">per month, typical home, vs 2 yrs ago</span>
                </p>
              )}
            </div>
          </div>
        </div>
        <p className="px-4 pt-2 text-xs text-[var(--ink-soft)] sm:px-0">
          Lines tie each facility to your address and flow toward it: ink live, amber under construction, blue announced; thicker means more load. Dashed ring: five miles. Green outlines: footprints measured from aerial imagery.
        </p>
      </div>

      {/* Five tiles: the whole brief at a glance. One opens at a time. */}
      <div className="mx-auto mt-6 max-w-6xl px-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" role="tablist" aria-label="Brief sections">
          {ORDER.map((id) => {
            const s = brief.sections[id]
            const isOpen = open === id
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={isOpen}
                aria-controls={`panel-${id}`}
                onClick={() => setOpen(isOpen ? null : id)}
                className={`tile tile-${s.status} flex min-h-[7.5rem] flex-col items-start p-3 text-left transition-colors ${isOpen ? 'bg-[var(--ink)] text-[var(--paper)]' : 'bg-white hover:bg-[var(--paper-deep)]'}`}
              >
                <span className={`text-xs font-semibold ${isOpen ? 'opacity-80' : `tag-${s.status}`}`}>
                  {STATUS_WORD[s.status]}{s.status !== 'unavailable' && <span className="num font-normal"> · {Math.round(s.confidence * 100)}%</span>}
                </span>
                <span className="mt-1 text-lg font-bold leading-tight">{SECTION_TITLES[id]}</span>
                <span className={`mt-1 line-clamp-3 text-[13px] leading-snug ${isOpen ? 'opacity-85' : 'text-[var(--ink-soft)]'}`}>{tileLine(s.summary)}</span>
              </button>
            )
          })}
        </div>

        {open && (
          <div id={`panel-${open}`} role="tabpanel" className="mt-6 border-t-2 border-[var(--ink)] pt-6">
            <SectionBlock id={open} section={brief.sections[open]} />
          </div>
        )}

        <details className="mt-8 border-t border-[var(--line)] pt-3">
          <summary className="cursor-pointer text-lg font-bold">
            Every claim, checked <span className="num text-sm font-normal text-[var(--ink-soft)]">· {brief.claims.length} claims, {supported} supported</span>
          </summary>
          <div className="mt-3"><Claims claims={brief.claims} /></div>
        </details>

        <details className="mt-3 border-t border-[var(--line)] pt-3">
          <summary className="cursor-pointer text-lg font-bold">
            Share it <span className="text-sm font-normal text-[var(--ink-soft)]">· the card carries the sources line</span>
          </summary>
          {h.percentile !== null && h.ai_rent_usd_per_month !== null && (
            <p className="mt-3 max-w-[64ch] text-[15px] text-[var(--ink-soft)]">
              {fmtMoney(h.ai_rent_usd_per_month)} a month puts this address above {h.percentile}% of US households, weighted by state population.
            </p>
          )}
          <div className="mt-4 max-w-3xl"><ShareCard brief={brief} /></div>
        </details>

        <p className="mt-6 text-xs text-[var(--ink-soft)]">
          Brief {brief.brief_id}, generated {new Date(brief.generated_at).toLocaleString('en-US')}, mode {brief.source_mode}. The address is not stored; the id is a hash of it.
        </p>
      </div>
    </main>
  )
}

function stateForError(err: unknown): State {
  if (!(err instanceof ApiError)) return { kind: 'error', message: 'Cannot reach the brief service.' }
  if (err.status === 404) return { kind: 'missing' }
  return { kind: 'error', message: `${err.status} ${err.detail}` }
}

// First sentence of the summary, for the tile.
function tileLine(summary: string): string {
  const m = summary.match(/^.*?[.!?](?=\s|$)/)
  return m ? m[0] : summary
}
