import { useEffect, useId, useState, type CSSProperties } from 'react'
import { getPulse, type PulseConstant, type ScaleRef } from '../lib/api'
import { fmtNice } from '../lib/format'

const MW_MIN = 20
const MW_MAX = 2000
const MW_SNAPS = [50, 100, 300, 1000] as const

// The range input moves in log steps across 20–2,000 MW, so a 50 MW edge site
// and a 1 GW campus both get room. Positions are 0–STEPS.
const STEPS = 1000
const LOG_MIN = Math.log(MW_MIN)
const LOG_SPAN = Math.log(MW_MAX) - LOG_MIN
// Within this many positions of a snap point, the thumb lands on it.
const SNAP_WITHIN = 18

export interface SliderConstants {
  home: PulseConstant
  loadFactor: PulseConstant
}

interface SliderData {
  constants: SliderConstants | null
  scale: ScaleRef[]
}

// getPulse() is one shared request per page load (the home page's pulse strip
// reads the same one); this only picks the two constants and the size
// references out of it.
let dataOnce: Promise<SliderData | null> | null = null
function loadData(): Promise<SliderData | null> {
  dataOnce ??= getPulse()
    .then((p) => {
      const c = p.constants
      const home = c?.us_home_kwh_per_year
      const loadFactor = c?.dc_load_factor
      return {
        constants: home && loadFactor && home.value > 0 ? { home, loadFactor } : null,
        scale: p.scale ?? [],
      }
    })
    .catch(() => {
      dataOnce = null // a later slider may try again
      return null
    })
  return dataOnce
}

function useSliderData(): SliderData | null {
  const [d, setD] = useState<SliderData | null>(null)
  useEffect(() => {
    let live = true
    loadData().then((v) => { if (live) setD(v) })
    return () => { live = false }
  }, [])
  return d
}

// "A hyperscale data center" reads "a hyperscale data center" mid-sentence.
function midSentence(name: string): string {
  return name.startsWith('A ') ? `a${name.slice(1)}` : name
}

// Where a size sits among the references: the one it matches (within 10 %),
// else the two it falls between. Plain comparison of the MW figures; the
// references themselves are reported, so each name links its page and quote.
function placeAmong(mw: number, rows: ScaleRef[]): { lead: string; refs: ScaleRef[] } | null {
  if (rows.length === 0) return null
  const near = rows
    .filter((r) => Math.abs(r.mw - mw) <= r.mw * 0.1)
    .sort((a, b) => Math.abs(a.mw - mw) - Math.abs(b.mw - mw))[0]
  if (near) return { lead: 'About the size of', refs: [near] }
  const below = [...rows].reverse().find((r) => r.mw < mw)
  const above = rows.find((r) => r.mw > mw)
  if (below && above) return { lead: 'Between', refs: [below, above] }
  if (above) return { lead: 'Smaller than', refs: [above] }
  return { lead: 'Bigger than', refs: [below!] }
}

function RefLink({ r }: { r: ScaleRef }) {
  return (
    <a href={r.source_url} target="_blank" rel="noreferrer" title={`${r.source_title}: “${r.quote}”`}>
      {midSentence(r.name)}
    </a>
  )
}

// The class a size falls in, anchored on the cited references: IBM's small
// (1 to 5 MW) and hyperscale (over 100 MW) tiers, xAI's Colossus (300 MW) and
// Meta's Prometheus (1 GW, "one of the first AI data centers of this size").
function sizeClass(mw: number): string {
  if (mw <= 5) return 'Small data center'
  if (mw < 100) return 'Mid-size data center'
  if (mw < 300) return 'Hyperscale data center'
  if (mw < 1000) return 'Large AI campus'
  return 'Gigawatt AI campus'
}

const PRESET_WORD: Record<number, string> = { 50: 'Mid-size', 100: 'Hyperscale', 300: 'Large AI', 1000: 'Gigawatt AI' }

function toPos(mw: number): number {
  const clamped = Math.min(MW_MAX, Math.max(MW_MIN, mw))
  return Math.round(((Math.log(clamped) - LOG_MIN) / LOG_SPAN) * STEPS)
}

// A round number of MW, as people say it: 25, 140, 650, 1,250.
function niceMw(raw: number): number {
  const step = raw < 100 ? 5 : raw < 1000 ? 10 : 50
  return Math.min(MW_MAX, Math.max(MW_MIN, Math.round(raw / step) * step))
}

// One keyboard step: the next round number up or down, in the same 5/10/50 MW
// units niceMw rounds to. An arrow key moves the range by one position, which
// the snap points and the rounding would otherwise swallow.
function stepMw(mw: number, dir: 1 | -1): number {
  const step = dir > 0 ? (mw < 100 ? 5 : mw < 1000 ? 10 : 50) : mw <= 100 ? 5 : mw <= 1000 ? 10 : 50
  return Math.min(MW_MAX, Math.max(MW_MIN, Math.round(mw / step) * step + dir * step))
}

function nextSnap(mw: number, dir: 1 | -1): number {
  const s = dir > 0 ? MW_SNAPS.find((x) => x > mw) : [...MW_SNAPS].reverse().find((x) => x < mw)
  return s ?? (dir > 0 ? MW_MAX : MW_MIN)
}

function keyMw(key: string, mw: number): number | null {
  switch (key) {
    case 'ArrowRight': case 'ArrowUp': return stepMw(mw, 1)
    case 'ArrowLeft': case 'ArrowDown': return stepMw(mw, -1)
    case 'PageUp': return nextSnap(mw, 1)
    case 'PageDown': return nextSnap(mw, -1)
    case 'Home': return MW_MIN
    case 'End': return MW_MAX
    default: return null
  }
}

function fromPos(pos: number): number {
  for (const s of MW_SNAPS) if (Math.abs(pos - toPos(s)) <= SNAP_WITHIN) return s
  return niceMw(Math.exp(LOG_MIN + (pos / STEPS) * LOG_SPAN))
}

// The engine's own arithmetic (app/scenario/model.py): MW × 1,000 kW/MW ×
// load factor × 8,760 h ÷ kWh per home. Shown with fmtNice, the same rounding
// as the scenario's homes counter, so 100 MW reads 64,900 in both places.
function homesFor(mw: number, c: SliderConstants): number {
  return (mw * 1000 * c.loadFactor.value * 8760) / c.home.value
}

type Props = {
  value: number
  onChange: (mw: number) => void
  disabled?: boolean
  // Optional: an id for the label to point at (the default is generated).
  id?: string
}

export default function MwSlider({ value, onChange, disabled = false, id }: Props) {
  const auto = useId()
  const inputId = id ?? `${auto}-mw`
  const ticksId = `${auto}-ticks`
  const noteId = `${auto}-note`
  const data = useSliderData()
  const c = data?.constants ?? null
  const scale = data?.scale ?? []
  const place = placeAmong(value, scale)
  const homes = c ? fmtNice(homesFor(value, c)) : null

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <label htmlFor={inputId} className="block text-sm text-[var(--ink-soft)]">
          Campus size
        </label>
        {/* Not a live region: aria-valuetext already speaks the value on each step. */}
        <p id={noteId} className="text-sm">
          <span className="wide num text-2xl font-bold leading-none">{value.toLocaleString('en-US')} MW</span>
          <span className="ml-2 font-semibold">{sizeClass(value)}</span>
          {homes !== null && c && (
            <span className="text-[var(--ink-soft)]">
              {' '}≈ <span className="num">{homes}</span> homes’ electricity{' '}
              <a
                href={c.home.source_url}
                target="_blank"
                rel="noreferrer"
                title={`${c.home.quote} (load factor ${c.loadFactor.value}, ${c.loadFactor.source_title})`}
                className="tag-modelled text-xs font-semibold no-underline hover:underline"
              >
                Modeled
              </a>
            </span>
          )}
        </p>
      </div>
      <input
        id={inputId}
        type="range"
        min={0}
        max={STEPS}
        step={1}
        list={ticksId}
        value={toPos(value)}
        disabled={disabled}
        aria-valuetext={`${value.toLocaleString('en-US')} megawatts, ${sizeClass(value).toLowerCase()}${homes !== null ? `, about ${homes} homes, modeled` : ''}`}
        aria-describedby={noteId}
        onChange={(e) => {
          const mw = fromPos(Number(e.target.value))
          if (mw !== value) onChange(mw)
        }}
        onKeyDown={(e) => {
          const mw = keyMw(e.key, value)
          if (mw === null) return
          e.preventDefault()
          if (mw !== value) onChange(mw)
        }}
        className="mw-range mt-3 w-full"
      />
      <datalist id={ticksId}>
        {MW_SNAPS.map((s) => <option key={s} value={toPos(s)} />)}
      </datalist>
      {/* The snap points as presets: a tap is quicker than a drag on a phone.
          On a phone they sit as an even row (under their ticks they would
          overlap); from sm up each sits under its tick. Each is 24 px tall. */}
      <div className="mt-2 flex justify-between gap-1 sm:relative sm:mt-1 sm:block sm:h-11" role="group" aria-label="Preset sizes">
        {MW_SNAPS.map((s) => (
          <button
            key={s}
            type="button"
            disabled={disabled}
            aria-pressed={value === s}
            onClick={() => onChange(s)}
            style={{ '--at': `${(toPos(s) / STEPS) * 100}%` } as CSSProperties}
            className={`mw-preset num min-h-6 px-1.5 py-1 text-xs sm:absolute sm:left-[var(--at)] sm:-translate-x-1/2 ${value === s ? 'font-bold text-[var(--ink)]' : 'text-[var(--ink-soft)]'}`}
          >
            <span className="block">{s >= 1000 ? `${s / 1000} GW` : `${s} MW`}</span>
            <span className="block text-[11px] font-normal leading-tight">{PRESET_WORD[s]}</span>
          </button>
        ))}
      </div>
      {place && (
        <div className="mt-3 text-sm">
          <p className="text-[var(--ink-soft)]">
            {place.lead}{' '}
            <RefLink r={place.refs[0]} /> ({place.refs[0].size})
            {place.refs[1] && (
              <>
                {' '}and <RefLink r={place.refs[1]} /> ({place.refs[1].size})
              </>
            )}
            .{' '}
            <span className="tag-reported text-xs font-semibold">Reported</span>
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-[var(--ink-soft)]">How big is that? Compare real data centers</summary>
            <ul className="mt-2 divide-y divide-[var(--line)] border-y border-[var(--line)]">
              {withYou(value, scale).map((r) =>
                r === 'you' ? (
                  <li key="you" className="py-2 font-semibold">
                    <span className="num">{value.toLocaleString('en-US')} MW</span>: this what-if
                    {homes !== null && <span className="font-normal text-[var(--ink-soft)]"> · about <span className="num">{homes}</span> homes’ electricity</span>}
                  </li>
                ) : (
                  <li key={r.id} className="py-2">
                    <p>
                      <a href={r.source_url} target="_blank" rel="noreferrer" title={`${r.source_title}: “${r.quote}”`} className="font-semibold">
                        {r.name}
                      </a>
                      <span className="text-[var(--ink-soft)]">: {r.size}</span>
                      {r.kind === 'frontier' && <span className="text-xs text-[var(--ink-soft)]"> · AI campus</span>}
                    </p>
                    <p className="text-[var(--ink-soft)]">
                      <span title={`“${r.detail_quote}”`}>{r.detail}</span>
                      {c && <> {homesPhrase(r, c)}</>}
                    </p>
                  </li>
                ),
              )}
            </ul>
            <p className="mt-2 text-xs text-[var(--ink-soft)]">
              Sizes and descriptions as the linked pages report them; for the AI campuses these are plans,
              not measured draw. Homes’ electricity is modeled: MW × load factor × 8,760 hours ÷ a home’s
              yearly use.
            </p>
          </details>
        </div>
      )}
    </div>
  )
}

// A row's size in homes' electricity, worded by how its MW reads.
function homesPhrase(r: ScaleRef, c: SliderConstants): string {
  const n = fmtNice(homesFor(r.mw, c))
  const lead = r.bound === 'up_to' ? 'Up to about' : r.bound === 'over' ? 'More than' : 'About'
  return `${lead} ${n} homes’ electricity.`
}

// The references in order with this what-if's own size slotted in.
function withYou(mw: number, rows: ScaleRef[]): (ScaleRef | 'you')[] {
  const at = rows.findIndex((r) => r.mw > mw)
  const out: (ScaleRef | 'you')[] = [...rows]
  out.splice(at === -1 ? rows.length : at, 0, 'you')
  return out
}
