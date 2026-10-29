import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Claims from '../components/Claims'
import GlanceTiles from '../components/GlanceTiles'
import GroundSteps from '../components/GroundSteps'
import HouseStrip from '../components/HouseStrip'
import MapView from '../components/MapView'
import { SectionBlock, type Readiness } from '../components/Sections'
import ShareCard from '../components/ShareCard'
import ShareMenu from '../components/ShareMenu'
import { ApiError, getBrief } from '../lib/api'
import { useLive } from '../lib/live'
import type { Brief, HouseTopic, Section, SectionId } from '../types'
import type { Live } from '../lib/live'
import { fmtMoney, fmtRange, localeOf, nearKm, nearWords, periodLabel, ringRadius } from '../lib/format'
import { publishRegion, regionOfBrief, useCurrentRegion } from '../lib/region'
import { STATUS_WORD, TOPIC_WORD, confidenceWord, sectionTitle } from '../lib/words'

const ORDER: SectionId[] = ['on_your_grid', 'coming', 'your_bill', 'protection', 'hearing']

type State = { kind: 'loading' } | { kind: 'missing' } | { kind: 'error'; message: string } | { kind: 'ready'; brief: Brief }

// One screen: the map with the headline on it, the concerns as tiles, the
// plain sentences, then the five sections the numbers come from, one open at
// a time. Everything else folds away.
export default function BriefPage() {
  const { key = '' } = useParams()
  const live = useLive(key)
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [open, setOpen] = useState<SectionId | null>(null)

  // A brief that is being made right now comes from the live store and
  // re-renders on every stage; anything else is fetched from the cache.
  const streaming = live !== undefined
  useEffect(() => {
    setOpen(null)
    if (streaming) return
    let cancelled = false
    setState({ kind: 'loading' })
    getBrief(key)
      .then((brief) => { if (!cancelled) setState({ kind: 'ready', brief }) })
      .catch((err: unknown) => { if (!cancelled) setState(stateForError(err)) })
    return () => { cancelled = true }
  }, [key, streaming])

  if (live) {
    return <BriefView brief={live.brief} live={live} open={open} setOpen={setOpen} />
  }
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

  return <BriefView brief={state.brief} open={open} setOpen={setOpen} />
}

function BriefView({ brief, live, open, setOpen }: { brief: Brief; live?: Live; open: SectionId | null; setOpen: (id: SectionId | null) => void }) {
  const a = brief.address
  const h = brief.headline
  const locale = localeOf(brief)
  const us = locale.country === 'US'
  // The brief's own region (found by its locale's country) names the footer's
  // sources and the geocoder's attribution line.
  const { regions } = useCurrentRegion()
  const region = regionOfBrief(regions, brief)
  const regionId = region?.id ?? null
  useEffect(() => {
    if (regionId) publishRegion(undefined, regionId)
  }, [regionId])
  // While the stream runs, facts are final but every sentence a model wrote
  // is a draft until the second model has checked its claims.
  const inProgress = live !== undefined && live.stage !== 'done'
  const nothingDrafted = inProgress && (brief.partial?.drafted ?? 0) === 0
  const supported = brief.claims.filter((c) => c.verdict === 'supported').length
  const bill = brief.sections.your_bill
  const facilities = [...(brief.sections.on_your_grid.facilities ?? []), ...(brief.sections.coming.facilities ?? [])].filter((f) => f.status !== 'rejected')
  const placed = facilities.filter((f) => typeof f.lat === 'number').length
  const withinMile = facilities.filter((f) => f.distance_km <= nearKm(locale.units)).length

  return (
    <main className="pb-16">
      <nav className="mx-auto flex max-w-6xl items-baseline justify-between px-4 pt-4 text-sm">
        <Link to="/" className="no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
        {brief.fixture && <span className="text-[var(--ink-soft)]">Fixture. Operators and sources are fictional.</span>}
        {brief.source_mode === 'agent' && <span className="text-[var(--ink-soft)]">Drafted by Muse Spark from its own knowledge. Checked, not measured.</span>}
        {brief.source_mode === 'full' && <span className="text-[var(--ink-soft)]">Facilities, utility and prices from public data. Sentences by Muse Spark, checked by Muse Spark Open.</span>}
      </nav>

      {live && live.stage !== 'done' && <Progress live={live} />}
      {live && live.stage === 'done' && <DoneLine live={live} brief={brief} />}

      {/* Hero: the map, with the headline card on top of it. */}
      <div className="relative mx-auto mt-3 max-w-6xl sm:px-4">
        <div className="relative">
          <MapView brief={brief} className="h-[52vh] min-h-[380px] w-full sm:h-[62vh]" />
          {/* The count on the map is the count in the headline, and it says so. */}
          {placed > 0 && (
            <p className="pointer-events-none absolute bottom-6 left-3 z-[1000] border-2 border-[var(--ink)] bg-[var(--paper)]/95 px-2.5 py-1.5 text-sm font-semibold">
              <span className="num">{placed}</span> {placed === 1 ? 'facility' : 'facilities'} plotted
              {withinMile > 0 && <span className="num font-normal text-[var(--ink-soft)]"> · {withinMile} {nearWords(locale.units)}</span>}
            </p>
          )}
        </div>
        <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3 sm:left-4 sm:right-auto sm:max-w-md sm:p-5">
          <div className="pointer-events-auto border-2 border-[var(--ink)] bg-[var(--paper)]/95 p-4 shadow-[6px_6px_0_var(--ink)] backdrop-blur-sm">
            <p className="text-sm text-[var(--ink-soft)]">{placeLine(a, us)}{a.utility ? ` · served by ${a.utility}` : ''}</p>
            <h1 className="sign mt-1 text-[clamp(1.9rem,5vw,3rem)]">{a.display}</h1>
            <div className="mt-3 flex items-end justify-between gap-4">
              {inProgress && (!h.one_liner || h.one_liner === NO_SUMMARY) ? (
                <p className="breathe max-w-[34ch] text-[15px] leading-snug text-[var(--ink-soft)]">Writing the summary from the facts…</p>
              ) : h.one_liner && (
                <p className={`max-w-[34ch] text-[15px] leading-snug ${inProgress && !nothingDrafted ? 'text-[var(--ink-soft)]' : ''}`}>
                  {inProgress && !nothingDrafted && <span className="chip-draft">Draft</span>}
                  {h.one_liner}
                </p>
              )}
              {h.ai_rent_usd_per_month !== null && (
                <p className="num shrink-0 text-right">
                  {/* An estimate is shown as a range, in the estimate colour, with the
                      same status word as its tile. Never a solid point estimate. */}
                  <span className="block text-3xl font-extrabold leading-none text-[var(--modelled)]">
                    {h.ai_rent_range_usd_per_month ? fmtRange(h.ai_rent_range_usd_per_month, locale.currency) : `about ${fmtMoney(h.ai_rent_usd_per_month, locale.currency)}`}
                  </span>
                  <span className="block text-xs text-[var(--ink-soft)]">a month, typical home, {periodWords(bill.price)}</span>
                  <span className="tag-modelled block text-xs font-semibold">
                    {STATUS_WORD.modelled}{bill.status !== 'unavailable' && <span className="font-normal"> · {confidenceWord(bill.confidence)}</span>}
                  </span>
                </p>
              )}
            </div>
          </div>
        </div>
        <p className="px-4 pt-2 text-xs text-[var(--ink-soft)] sm:px-0">
          {placed > 0 && <><span className="num">{placed}</span> {placed === 1 ? 'line ties the one facility' : 'lines tie each facility'} to your address and flow toward it: ink live, amber under construction, blue announced; thicker means more load. </>}
          Dashed ring: {ringRadius(locale.units)}. Green outlines: footprints measured from aerial imagery.
        </p>
      </div>

      {/* The concerns, as tiles: a number where the engine has one, a sentence
          where a model wrote one, Not public with who to ask where nobody publishes. */}
      <GlanceTiles glance={brief.glance} checking={inProgress} />

      {/* The plain-language layer. The sections below are for the reporter; this is for everyone. */}
      {brief.at_your_house && brief.at_your_house.length > 0 && (
        <div className="mt-8"><HouseStrip lines={brief.at_your_house} checking={inProgress} locale={locale} /></div>
      )}

      {/* Where the numbers come from: five sections, one open at a time. */}
      <div className="mx-auto mt-10 max-w-6xl px-4">
        <h2 className="text-2xl font-bold leading-none">Where this comes from</h2>
        <p className="mt-2 max-w-[60ch] text-sm text-[var(--ink-soft)]">
          The five parts behind the tiles. Open one for the facilities, the prices, the tariff text and the hearing quotes, each with its sources.
        </p>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-5" role="tablist" aria-label="Brief sections">
          {ORDER.map((id) => {
            const s = brief.sections[id]
            const isOpen = open === id
            const r = readiness(brief, id, inProgress)
            const pending = r === 'pending'
            const soft = pending || r === 'draft'
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={isOpen}
                aria-controls={`panel-${id}`}
                onClick={() => setOpen(isOpen ? null : id)}
                className={`tile tile-${s.status} flex min-h-[7.5rem] flex-col items-start p-3 text-left transition-colors ${pending ? 'breathe' : ''} ${isOpen ? 'bg-[var(--ink)] text-[var(--paper)]' : 'bg-white hover:bg-[var(--paper-deep)]'}`}
              >
                <span className={`text-xs font-semibold ${isOpen ? 'opacity-80' : soft ? 'text-[var(--ink-soft)]' : `tag-${s.status}`}`}>
                  {pending ? 'Writing' : r === 'draft' ? 'Draft' : STATUS_WORD[s.status]}
                  {r === 'final' && s.status !== 'unavailable' && <span className="font-normal"> · {confidenceWord(s.confidence)}</span>}
                  {(r === 'draft' || r === 'engine') && <span className="font-normal"> · not yet checked</span>}
                </span>
                <span className="mt-1 text-lg font-bold leading-tight">{sectionTitle(id, locale)}</span>
                <span className={`mt-1 line-clamp-3 text-[13px] leading-snug ${isOpen ? 'opacity-85' : 'text-[var(--ink-soft)]'}`}>{pending ? 'Writing this part from the facts above…' : tileLine(id, s)}</span>
              </button>
            )
          })}
        </div>

        {open && (
          <div id={`panel-${open}`} role="tabpanel" className="mt-6 border-t-2 border-[var(--ink)] pt-6">
            <SectionBlock id={open} section={brief.sections[open]} readiness={readiness(brief, open, inProgress)} locale={locale} />
          </div>
        )}

        <details className="mt-8 border-t border-[var(--line)] pt-3">
          <summary className="cursor-pointer text-lg font-bold">
            Every claim, checked <span className="num text-sm font-normal text-[var(--ink-soft)]">· {live && live.stage === 'verifying' ? `checking ${live.verified} of ${live.claims}` : inProgress ? `${brief.claims.length} claims drafted, none checked yet` : `${brief.claims.length} claims, ${supported} supported`}</span>
          </summary>
          <div className="mt-3"><Claims claims={brief.claims} checking={inProgress} locale={locale} /></div>
        </details>

        {/* The card leaves this page, so it waits for the check: nothing unverified gets shared. */}
        <div className="mt-3 border-t border-[var(--line)] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className={`text-lg font-bold ${inProgress ? 'text-[var(--ink-soft)]' : ''}`}>
              Share it <span className="text-sm font-normal text-[var(--ink-soft)]">· {inProgress ? 'available once every claim is checked' : 'the card carries the sources line and says it is AI-assisted'}</span>
            </p>
            <ShareMenu kind="brief" id={brief.brief_id} disabled={inProgress} />
          </div>
          {!inProgress && (
          <details className="mt-2">
            <summary className="cursor-pointer text-sm text-[var(--ink-soft)]">Preview the card</summary>
            {us && h.percentile !== null && h.ai_rent_usd_per_month !== null && (
              <p className="mt-3 max-w-[64ch] text-[15px] text-[var(--ink-soft)]">
                About {fmtMoney(h.ai_rent_usd_per_month)} a month puts this address above {h.percentile}% of US households, weighted by state population. Our estimate from the state's average price and a typical home's usage.
              </p>
            )}
            <div className="mt-3 max-w-3xl border border-[var(--line)]"><ShareCard brief={brief} /></div>
          </details>
          )}
        </div>

        <p className="mt-6 text-xs text-[var(--ink-soft)]">
          Brief {brief.brief_id}, generated {new Date(brief.generated_at).toLocaleString(locale.language)}. The id is a hash of the address; the address itself is stored only inside this brief.
        </p>
      </div>
    </main>
  )
}

// The brief is built in three steps and the strip says which one it is in,
// in the words of what is being fetched and written: the facts land in
// seconds, the sentences and the check take the rest.
const WRITING: HouseTopic[] = ['bill', 'noise', 'land', 'water', 'taxes']

function Progress({ live }: { live: Live }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const elapsed = Math.max(0, Math.round((now - live.startedAt) / 1000))
  const p = live.brief.partial
  const writing = live.stage === 'ground' || live.stage === 'drafting'
  const checking = live.stage === 'verifying'
  const written = new Set((live.brief.at_your_house ?? []).map((l) => l.topic))
  const houseIn = p?.house ?? false
  const sectionsDone = p ? p.sections - p.pending.length : 0
  return (
    <div className="sticky top-0 z-[1100] mx-auto mt-3 max-w-6xl px-4" aria-live="polite">
      <div className="border-2 border-[var(--ink)] bg-white px-3 py-2 text-sm shadow-[4px_4px_0_var(--ink)]">
        <ol className="grid gap-y-1">
          <Row word="Facts" state="done">
            <GroundSteps steps={live.steps} />
          </Row>
          <Row word="Writing" state={writing ? 'active' : 'done'}>
            <span className="inline-flex flex-wrap gap-x-3 gap-y-1">
              {WRITING.map((t) => {
                const on = written.has(t)
                const settled = on || houseIn || !writing
                return (
                  <span key={t} className={`inline-flex items-center gap-1 ${on ? 'text-[var(--ink)]' : settled ? 'text-[var(--ink-soft)]' : 'breathe text-[var(--ink-soft)]'}`}>
                    <span aria-hidden className="num w-3 text-center font-semibold">{on ? '✓' : settled ? '–' : '·'}</span>
                    {TOPIC_WORD[t].toLowerCase()}
                  </span>
                )
              })}
              <span className="text-[var(--ink-soft)]">· sections <span className="num">{sectionsDone}</span> of {p?.sections ?? ORDER.length}</span>
            </span>
          </Row>
          <Row word="Checking" state={checking ? 'active' : 'todo'}>
            {checking ? <><span className="num">{live.verified}</span> of <span className="num">{live.claims}</span> claims against their pages</> : 'every claim against its page'}
          </Row>
        </ol>
        <p className="mt-1.5 flex flex-wrap justify-between gap-x-4 text-xs text-[var(--ink-soft)]">
          <span>Facts are final. Sentences are drafts until every claim is checked against its page.</span>
          <span className="num">{elapsed}s</span>
        </p>
        {live.stage === 'error' && <p className="mt-1 text-[var(--reported)]" role="alert">{live.error} The facts above stand; the sentences could not be finished.</p>}
      </div>
    </div>
  )
}

function Row({ word, state, children }: { word: string; state: 'done' | 'active' | 'todo'; children: React.ReactNode }) {
  return (
    <li className={`flex flex-wrap items-baseline gap-x-2 ${state === 'todo' ? 'text-[var(--line)]' : ''}`}>
      <span aria-hidden className={`inline-block h-2.5 w-2.5 shrink-0 self-center border border-[var(--ink)] ${state === 'done' ? 'bg-[var(--ink)]' : state === 'active' ? 'bg-[var(--modelled)]' : 'bg-transparent'}`} />
      <span className={`w-16 font-semibold ${state === 'active' ? 'breathe' : state === 'todo' ? '' : 'text-[var(--ink)]'}`}>{word}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </li>
  )
}

// Once the stream ends, one quiet line marks the transition from draft to
// checked, so a reader who scrolled past the progress strip still sees it.
function DoneLine({ live, brief }: { live: Live; brief: Brief }) {
  const supported = brief.claims.filter((c) => c.verdict === 'supported').length
  const secs = live.endedAt ? Math.max(0, Math.round((live.endedAt - live.startedAt) / 1000)) : null
  return (
    <p className="mx-auto mt-3 max-w-6xl px-4 text-sm text-[var(--ink-soft)]" role="status">
      <span className="font-semibold text-[var(--measured)]">✓ Checked.</span> <span className="num">{brief.claims.length}</span> claims, <span className="num">{supported}</span> supported{secs !== null && <>, in <span className="num">{secs}</span> s</>}.
    </p>
  )
}

const NO_SUMMARY = 'Not enough public information to summarize this address yet.'

// Facts are final from the first event; a section's sentences are a draft
// until the check ends, unless the engine wrote every claim from the data.
function readiness(brief: Brief, id: SectionId, inProgress: boolean): Readiness {
  if (!inProgress) return 'final'
  if (brief.partial?.pending.includes(id)) return 'pending'
  const claims = brief.claims.filter((c) => c.section === id)
  return claims.length > 0 && claims.every((c) => c.drafted_by === 'engine') ? 'engine' : 'draft'
}

// The line over the address: "Loudoun County, VA" in the US; outside it the
// county field is the planning authority and is printed as it comes.
function placeLine(a: Brief['address'], us: boolean) {
  if (us) return `${a.county ? `${a.county} County, ` : ''}${a.state ?? ''}`
  return a.county ?? ''
}

// Annual utility data is labelled by its years; a semiannual series by its
// half-years ("H1 2026 vs H1 2024"); a series to the present says "vs 2 yrs ago".
function periodWords(price: Section['price']) {
  const half = periodLabel(price)
  if (half) return half.both
  const asOf = price?.as_of
  const windowMonths = price?.window_months
  if (asOf && asOf.endsWith('-12')) {
    const year = Number(asOf.slice(0, 4))
    return `${year} vs ${year - Math.max(1, Math.floor((windowMonths ?? 24) / 12))}`
  }
  return 'vs 2 yrs ago'
}

function stateForError(err: unknown): State {
  if (!(err instanceof ApiError)) return { kind: 'error', message: 'Cannot reach the brief service.' }
  if (err.status === 404) return { kind: 'missing' }
  return { kind: 'error', message: `${err.status} ${err.detail}` }
}

// One line for the tile. Protection answers the question the card exists for,
// does it shield you, from the structured data; the others take the first
// sentence of the summary.
function tileLine(id: SectionId, s: Section): string {
  if (id === 'protection' && s.tariff && s.status !== 'unavailable') {
    const t = s.tariff
    if (t.kind === 'connection_policy') {
      // Said only by its stated aim, never as a finding about bills.
      const name = t.name ?? 'A connection policy'
      if (t.protects_households === false) return `No. ${name} is ${t.large_load_tariff === 'in_force' ? 'in force' : 'on record'}; keeping costs off household bills is not its stated aim.`
      if (t.protects_households === true) return `Yes, in part. ${name} aims to keep some build-out costs off household bills.`
      return 'Not known whether anything shields household bills.'
    }
    const name = t.name ?? 'A large-load tariff'
    if (t.protects_households === true) return `Yes, in part. ${name} is in force and keeps some build-out costs off household bills.`
    if (t.protects_households === false) {
      return t.large_load_tariff === 'none_found' ? 'No. No large-load tariff in this state; new load is served under the general tariff.' : `No. ${name} does not shield household bills.`
    }
    if (t.large_load_tariff === 'proposed') return `Not yet. ${name} is proposed, not approved; nothing shields household bills today.`
    return 'Not known whether anything shields household bills.'
  }
  const m = s.summary.match(/^.*?[.!?](?=\s|$)/)
  return m ? m[0] : s.summary
}
