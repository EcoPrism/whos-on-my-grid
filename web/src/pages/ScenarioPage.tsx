import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Claims from '../components/Claims'
import HouseStrip from '../components/HouseStrip'
import HypotheticalBanner from '../components/HypotheticalBanner'
import ImpactCounters from '../components/ImpactCounters'
import Interpretation from '../components/Interpretation'
import MwSlider from '../components/MwSlider'
import ScenarioMap, { type LatLonPoint } from '../components/ScenarioMap'
import ShareMenu from '../components/ShareMenu'
import Timeline from '../components/Timeline'
import { ApiError, createScenario, getScenario } from '../lib/api'
import { setLiveScenario, useLiveScenario } from '../lib/live'
import { scenarioMessage, shareable } from '../lib/scenario'
import type { Cooling, Scenario, ScenarioInputs } from '../types'

const DISCLOSURE = 'Hypothetical. Modelled, not measured.'

const COOLING: { value: Cooling; label: string; note: string }[] = [
  { value: 'evaporative', label: 'Evaporative', note: 'cools by evaporating water' },
  { value: 'closed_loop', label: 'Closed loop', note: 'recirculates water to the chips' },
]

// A change to the controls waits this long for the next one before asking.
const DEBOUNCE_MS = 300

type State = { kind: 'loading' } | { kind: 'missing' } | { kind: 'error'; message: string }

// The what-if page: one hypothetical campus dropped on a ZIP code. The
// baseline (the campuses already there, the utility, the tariff) is measured;
// every number about the new campus is the engine's arithmetic, and the
// banner at the top says so for as long as the page is open.
export default function ScenarioPage() {
  const { key = '' } = useParams()
  const live = useLiveScenario(key)
  const [state, setState] = useState<State>({ kind: 'loading' })

  // A scenario made on this visit (from home, or by the controls below) is in
  // the live store already; anything else is fetched from the cache and put
  // there, so going back to it opens at once.
  const have = live !== undefined
  useEffect(() => {
    if (have) return
    let cancelled = false
    setState({ kind: 'loading' })
    getScenario(key)
      .then((s) => { if (!cancelled) setLiveScenario(key, s) })
      .catch((err: unknown) => { if (!cancelled) setState(stateForError(err)) })
    return () => { cancelled = true }
  }, [key, have])

  if (live) return <ScenarioView scenario={live} routeKey={key} />

  return (
    <>
      <HypotheticalBanner text={DISCLOSURE} />
      <main className="mx-auto max-w-3xl px-4 py-24">
        {state.kind === 'loading' && <p className="text-[var(--ink-soft)]">Loading the what-if…</p>}
        {state.kind === 'missing' && (
          <>
            <h1 className="sign text-5xl">No what-if with that id</h1>
            <p className="mt-6">What-ifs are kept by their inputs, and this one is not in the cache. <Link to="/">Drop a campus from the home page to make it again.</Link></p>
          </>
        )}
        {state.kind === 'error' && (
          <>
            <h1 className="sign text-5xl">Could not load the what-if</h1>
            <p className="mt-6" role="alert">{state.message} <Link to="/">Back to the home page.</Link></p>
          </>
        )}
      </main>
    </>
  )
}

type Controls = Pick<ScenarioInputs, 'mw' | 'cooling' | 'pin'>

function ScenarioView({ scenario: s, routeKey }: { scenario: Scenario; routeKey: string }) {
  const nav = useNavigate()
  // What the controls show. Null means "the scenario's own inputs"; a value
  // means the reader has moved something and the engine is (about to be) asked.
  const [draft, setDraft] = useState<Controls | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Said once the newest answer lands: the engine's echoed size and cooling,
  // never the ZIP or the pin.
  const [announce, setAnnounce] = useState('')
  const seq = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  // The id this view navigated to itself; any other change of route (back,
  // a link) resets the controls to the scenario it lands on.
  const ownKey = useRef(routeKey)

  useEffect(() => {
    if (routeKey === ownKey.current) return
    ownKey.current = routeKey
    window.clearTimeout(timer.current)
    seq.current += 1
    setDraft(null)
    setBusy(false)
    setError(null)
  }, [routeKey])

  // Leaving the page drops a pending change and any answer still on its way.
  useEffect(() => () => {
    window.clearTimeout(timer.current)
    seq.current += 1
  }, [])

  const { mw, cooling, pin } = s.inputs
  const controls = useMemo<Controls>(() => draft ?? { mw, cooling, pin }, [draft, mw, cooling, pin])
  const zip = s.inputs.zip

  // Every change asks the engine again, 300 ms after the last one. Only the
  // newest answer is used; an older one that lands late is dropped.
  const change = useCallback((next: Partial<Controls>) => {
    const merged = { ...controls, ...next }
    const mine = ++seq.current
    setDraft(merged)
    setBusy(true)
    setError(null)
    setAnnounce('')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      createScenario({ zip, ...merged })
        .then((made) => {
          if (mine !== seq.current) return
          setLiveScenario(made.scenario_id, made)
          setBusy(false)
          setAnnounce(
            `Updated: ${made.inputs.mw.toLocaleString('en-US')} MW, ${made.inputs.cooling === 'closed_loop' ? 'closed loop' : 'evaporative'} cooling. Modelled.`,
          )
          if (made.scenario_id !== ownKey.current) {
            ownKey.current = made.scenario_id
            nav(`/what-if/${made.scenario_id}`, { replace: true })
          }
        })
        .catch((err: unknown) => {
          if (mine !== seq.current) return
          // Put the controls back on the scenario being shown, so the slider,
          // radios, pin and Share all agree with the numbers on the page.
          setDraft(null)
          setBusy(false)
          setError(scenarioMessage(err))
        })
    }, DEBOUNCE_MS)
  }, [controls, zip, nav])

  const onPinMove = useCallback((pin: LatLonPoint) => change({ pin }), [change])

  // The explanation lands on the scenario it was asked for; the page re-renders
  // from the store with no navigation.
  const onInterpreted = useCallback((made: Scenario) => setLiveScenario(made.scenario_id, made), [])

  const centre = { lat: s.place.lat, lon: s.place.lon }
  // Land is linear in MW in the engine (MW × acres per MW), so while the
  // slider moves the footprint follows the engine's own ratio; the answer
  // replaces it a moment later.
  const land = s.impact.land
  const acres = land ? (land.acres / s.inputs.mw) * controls.mw : 0
  const facilities = s.baseline.facilities.filter((f) => f.status !== 'rejected')
  const placed = facilities.filter((f) => typeof f.lat === 'number').length
  const count = s.baseline.facility_count ?? facilities.length
  const offCentre = controls.pin !== null && (Math.abs(controls.pin.lat - centre.lat) > 1e-5 || Math.abs(controls.pin.lon - centre.lon) > 1e-5)
  // From the first change until the newest answer lands, the numbers below are the last answer's.
  const pending = busy
  const canShare = shareable(s) && !pending
  const supported = s.claims.filter((c) => c.verdict === 'supported').length
  const verifierOn = s.claims.some((c) => c.verified_by)
  const coolingWord = COOLING.find((c) => c.value === s.inputs.cooling)?.label.toLowerCase() ?? s.inputs.cooling
  const u = s.baseline.utility
  const coolingId = useId()

  return (
    <>
      <HypotheticalBanner text={s.disclosure} />
      <main className="pb-16">
        <nav className="mx-auto flex max-w-6xl flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 pt-4 text-sm">
          <Link to="/" className="shrink-0 whitespace-nowrap no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
          <span className="text-[var(--ink-soft)] sm:text-right">Campuses, utility and tariff from public data. The new campus is arithmetic over cited figures; no model wrote these numbers.</span>
        </nav>

        {/* Hero: the map, with the place and the campus on a card on top of it. */}
        <div className="relative mx-auto mt-3 max-w-6xl sm:px-4">
          <ScenarioMap
            center={centre}
            pin={controls.pin}
            acres={acres}
            facilities={facilities}
            onPinMove={onPinMove}
            className="h-[52vh] min-h-[380px] w-full sm:h-[62vh]"
          />
          <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3 sm:left-4 sm:right-auto sm:max-w-md sm:p-5">
            <div className="pointer-events-auto border-2 border-[var(--ink)] bg-[var(--paper)]/95 p-4 shadow-[6px_6px_0_var(--ink)] backdrop-blur-sm">
              <p className="text-sm text-[var(--ink-soft)]">{s.place.county ? `${s.place.county} County, ` : ''}{s.place.state}{u ? ` · served by ${u.name}` : ''}</p>
              <h1 className="sign mt-1 text-[clamp(1.9rem,5vw,3rem)]">{s.place.display}</h1>
              <p className={`mt-3 text-[15px] leading-snug transition-opacity ${pending ? 'opacity-60' : ''}`} aria-busy={pending || undefined}>
                A hypothetical <span className="num font-bold text-[var(--modelled)]">{s.inputs.mw.toLocaleString('en-US')} MW</span> campus with {coolingWord} cooling.
                <span className="tag-modelled ml-1 text-xs font-semibold">Modeled</span>
                {pending && <span className="ml-1 text-xs text-[var(--ink-soft)]">(updating)</span>}
              </p>
              <p className="mt-1 text-sm text-[var(--ink-soft)]">
                <span className="num font-semibold text-[var(--ink)]">{count}</span> {count === 1 ? 'data center is' : 'data centers are'} already within reach
                <span className="tag-measured ml-1 text-xs font-semibold">Measured</span>
              </p>
            </div>
          </div>
          <p className="px-4 pt-2 text-xs text-[var(--ink-soft)] sm:px-0">
            The dashed square is the campus footprint, modelled from its size. Drag the plate, click the map, or focus the plate and use the arrow keys to move it.
            Lines run from it to the centre of the ZIP code{placed > 0 && <> and to the <span className="num">{placed}</span> {placed === 1 ? 'campus' : 'campuses'} already mapped: ink live, amber under construction, blue announced</>}.
          </p>
        </div>

        <div className="mx-auto mt-6 max-w-6xl px-4">
          {/* The controls. Each change asks the engine again and the page follows. */}
          <section aria-label="Change the campus" className="border-2 border-[var(--ink)] bg-white p-4 sm:p-5">
            <div className="grid gap-x-10 gap-y-6 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <MwSlider value={controls.mw} onChange={(mw) => change({ mw })} />
              <fieldset>
                <legend className="text-sm text-[var(--ink-soft)]">Cooling</legend>
                <div className="seg mt-2 inline-flex">
                  {COOLING.map((c) => (
                    <label key={c.value} className="seg-option" title={c.note}>
                      <input
                        type="radio"
                        name={`${coolingId}-cooling`}
                        value={c.value}
                        checked={controls.cooling === c.value}
                        onChange={() => change({ cooling: c.value })}
                        className="sr-only"
                      />
                      <span className="block px-4 py-2 text-[15px]">{c.label}</span>
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-sm text-[var(--ink-soft)]">{COOLING.find((c) => c.value === controls.cooling)?.note}.</p>
                {offCentre && (
                  <button type="button" onClick={() => change({ pin: null })} className="mt-3 text-sm underline underline-offset-2">
                    Put the campus back on the ZIP centre
                  </button>
                )}
              </fieldset>
            </div>
            <div className="mt-4 flex min-h-6 flex-wrap items-center gap-3 text-sm" aria-live="polite">
              {busy && (
                <span className="inline-flex items-center gap-2 text-[var(--ink-soft)]">
                  <span className="spinner" aria-hidden /> Working it out…
                </span>
              )}
              {error && <span role="alert">{error}</span>}
              {!busy && !error && announce && <span className="sr-only">{announce}</span>}
            </div>
          </section>

          <div className={`mt-6 transition-opacity ${pending ? 'opacity-60' : ''}`} aria-busy={pending || undefined}>
            <ImpactCounters impact={s.impact} lines={s.lines} />
          </div>

          <div className={`mt-8 transition-opacity ${pending ? 'opacity-60' : ''}`} aria-busy={pending || undefined}>
            <Timeline months={s.impact.timeline?.construction_months ?? null} impact={s.impact} />
          </div>

          {/* A model's paragraph about the numbers above: Reported, gated, optional. */}
          <div className={`mt-10 transition-opacity ${pending && !s.interpretation ? 'opacity-60' : ''}`}>
            <Interpretation key={s.scenario_id} scenario={s} disabled={pending} onScenario={onInterpreted} />
          </div>
        </div>

        {s.lines.length > 0 && (
          <div className={`mt-8 transition-opacity ${pending ? 'opacity-60' : ''}`} aria-busy={pending || undefined}>
            <HouseStrip lines={s.lines} />
          </div>
        )}

        <div className="mx-auto mt-6 max-w-6xl px-4">
          <details className={`mt-2 border-t border-[var(--line)] pt-3 transition-opacity ${pending ? 'opacity-60' : ''}`} aria-busy={pending || undefined}>
            <summary className="cursor-pointer text-lg font-bold">
              Every figure, cited{' '}
              <span className="num text-sm font-normal text-[var(--ink-soft)]">
                · {verifierOn ? `${s.claims.length} claims, ${supported} supported` : `${s.claims.length} claims, not checked by a second model on this server`}
              </span>
            </summary>
            <div className="mt-3"><Claims claims={s.claims} /></div>
          </details>

          {/* The card leaves the page, so it carries the same disclosure as the banner. */}
          <div className="mt-3 border-t border-[var(--line)] pt-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className={`text-lg font-bold ${canShare ? '' : 'text-[var(--ink-soft)]'}`}>
                Share it{' '}
                <span className="text-sm font-normal text-[var(--ink-soft)]">
                  · {pending ? 'available once the new numbers arrive' : canShare ? 'the card says it is hypothetical and carries the sources line' : 'available once every claim is checked'}
                </span>
              </p>
              <ShareMenu kind="scenario" id={s.scenario_id} disabled={!canShare} />
            </div>
          </div>

          <p className="mt-6 text-xs text-[var(--ink-soft)]">
            What-if {s.scenario_id}, worked out {new Date(s.generated_at).toLocaleString('en-US')}. The id is a hash of the inputs; nothing about who asked is stored.
          </p>
        </div>
      </main>
    </>
  )
}

// A 404 is its own page; every other failure reads as the controls' errors do.
function stateForError(err: unknown): State {
  if (err instanceof ApiError && err.status === 404) return { kind: 'missing' }
  return { kind: 'error', message: scenarioMessage(err) }
}
