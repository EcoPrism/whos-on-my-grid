import { useEffect, useId, useRef, useState } from 'react'
import { fmtAcres, fmtNice, fmtUsd } from '../lib/format'
import { basisFor, type Basis } from '../lib/glance'
import { useAnimatedNumber, usePrefersReducedMotion } from '../lib/motion'
import { STATUS_GLOSS, STATUS_WORD, confidenceWord } from '../lib/words'
import type { HouseLine, Impact, Status } from '../types'
import { SourceLink } from './Sections'

const COUNT_MS = 900

type Props = {
  impact: Impact
  // The scenario's strip lines, to find the sources behind each counter.
  lines?: HouseLine[]
}

// Four numbers the engine worked out: homes' worth of electricity, gallons a
// day, acres, and the bill. Each ticks up from zero when it first appears and
// eases to a new value when the inputs change; each is tagged modelled and
// opens its working on tap. A block the engine left out (a constant with no
// cited page) shows "not known" instead of a number.
export default function ImpactCounters({ impact, lines }: Props) {
  // Counting starts after the first paint, so the counters tick up from zero.
  // Under reduced motion the final numbers show from the first paint.
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const k = (n: number | null | undefined) => ((shown || reduced) && n != null ? n : 0)

  const { power, water, land, bill } = impact
  const homes = useAnimatedNumber(k(power?.homes_equivalent), COUNT_MS)
  const gwh = useAnimatedNumber(k(power?.gwh_per_year), COUNT_MS)
  // With no cited kWh-per-home figure the tile shows GWh a year instead, so a
  // modelled number never sits under a "Not known" tag.
  const homesKnown = power?.homes_equivalent != null
  const gallons = useAnimatedNumber(k(water?.gal_per_day), COUNT_MS)
  const acres = useAnimatedNumber(k(land?.acres), COUNT_MS)
  const range = bill.range_usd_per_month
  const billLo = useAnimatedNumber(k(range?.[0]), COUNT_MS)
  const billHi = useAnimatedNumber(k(range?.[1]), COUNT_MS)

  const share = power?.share_of_utility_homes
  return (
    <section aria-label="What it would add, modelled">
      <ul className="grid gap-x-6 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
        <Counter
          label={homesKnown || !power ? 'Homes’ worth of electricity' : 'Electricity a year (GWh)'}
          value={!power ? null : homesKnown ? fmtNice(homes) : fmtNice(gwh)}
          final={!power ? null : homesKnown ? `${fmtNice(power.homes_equivalent!)} homes` : `${fmtNice(power.gwh_per_year)} GWh a year`}
          sub={power && homesKnown
            ? `${fmtNice(power.gwh_per_year)} GWh a year${share != null ? `, ${pctOf(share)} of this utility’s homes` : ''}`
            : undefined}
          basis={basisFor(power, 'grid', lines)}
        />
        <Counter
          label="Gallons of water a day"
          value={water ? fmtNice(gallons) : null}
          final={water ? `${fmtNice(water.gal_per_day)} gallons a day` : null}
          sub={water
            ? water.gal_per_day === 0
              ? 'None evaporated for cooling'
              : water.homes_equivalent != null ? `What ${fmtNice(water.homes_equivalent)} homes use` : undefined
            : undefined}
          basis={basisFor(water, 'water', lines)}
        />
        <Counter
          label="Acres of land"
          value={land ? fmtAcres(acres) : null}
          final={land ? `${fmtAcres(land.acres)} acres` : null}
          sub={land?.football_fields != null ? `About ${fmtAcres(land.football_fields)} football fields` : undefined}
          basis={basisFor(land, 'land', lines)}
        />
        <Counter
          label="Your bill, a month"
          value={billValue(bill.kind, range, billLo, billHi)}
          final={billValue(bill.kind, range, range?.[0] ?? 0, range?.[1] ?? 0)}
          sub={BILL_SUB[bill.kind]}
          unknown={bill.kind === 'unknown' && !range}
          basis={basisFor(bill, 'bill', lines)}
        />
      </ul>
    </section>
  )
}

const BILL_SUB: Record<Impact['bill']['kind'], string> = {
  shielded: 'A large-load tariff here shields households',
  partial: 'A tariff here covers part of the cost',
  exposed: 'No tariff found that shields households',
  unknown: 'Not enough on record to work it out',
}

function billValue(kind: Impact['bill']['kind'], range: [number, number] | null, lo: number, hi: number): string {
  if (kind === 'shielded') return 'Shielded'
  if (!range) return kind === 'partial' ? 'Partly shielded' : 'Unknown'
  return `+${fmtUsd(lo)} to ${fmtUsd(hi)}`
}

function pctOf(v: number): string {
  const p = v * 100
  if (p > 0 && p < 0.1) return 'under 0.1%'
  return p < 1 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`
}

export type CounterProps = {
  label: string
  status?: Status // the kind of evidence behind the tile; the what-if's counters are all modelled
  value: string | null // what is on screen now (animating); null when there is no number
  final: string | null // the settled value, for screen readers
  text?: string // a sentence in place of a number (a model's line on a brief tile)
  sub?: string
  unknown?: boolean // nothing is published: the Not public word stands in for the number
  confidence?: number
  draft?: boolean // a model's sentence the second model has not checked yet
  basis?: Basis
  size?: 'big' | 'small' // the what-if's four counters are big; six brief tiles share a row
}

// One tile: a label, a big number (or a short sentence), a line under it, the
// status word and, on tap, the working. Shared by the what-if counters and the
// brief's glance tiles.
export function Counter({ label, status = 'modelled', value, final, text, sub, unknown = false, confidence, draft = false, basis, size = 'big' }: CounterProps) {
  const sentence = value === null && Boolean(text)
  const tone: Status = unknown || (value === null && !sentence) ? 'unavailable' : status
  const known = tone !== 'unavailable'
  // The Not public word already stands where the number would be: no second tag under it.
  const wordShown = !known && value === null && !sentence
  const numSize = size === 'big' ? 'text-[clamp(2rem,5vw,2.75rem)]' : 'text-[clamp(1.6rem,2.6vw,2.1rem)]'
  return (
    <li className={`tile tile-${tone} pt-3`}>
      <h3 className="text-sm font-semibold leading-tight text-[var(--ink-soft)]">{label}</h3>
      {sentence ? (
        <p className={`mt-2 text-[15px] leading-snug ${draft ? 'text-[var(--ink-soft)]' : ''}`}>
          {draft && <span className="chip-draft">Draft</span>}
          {text}
        </p>
      ) : (
        <>
          {/* The ticking number is hidden from screen readers; they get the final one. */}
          <p
            className={`wide num mt-2 font-bold leading-none tracking-tight ${value === null ? 'text-2xl' : numSize}`}
            aria-hidden
          >
            {value ?? (unknown ? STATUS_WORD.unavailable : '—')}
          </p>
          <p className="sr-only">{value !== null ? final : STATUS_WORD.unavailable}</p>
        </>
      )}
      {sub && <p className="mt-2 text-sm leading-snug text-[var(--ink-soft)]">{sub}</p>}
      {/* relative: the working's popover is anchored to this row, so it is never wider than the tile. */}
      {(!wordShown || (basis && basis.text)) && (
        <div className="relative mt-2 flex flex-wrap items-center gap-x-2 text-xs">
          {!wordShown && (
            <span className={`tag-${tone} font-semibold`}>
              {draft ? 'Draft' : STATUS_WORD[tone]}
              {known && !draft && confidence != null && <span className="font-normal text-[var(--ink-soft)]"> · {confidenceWord(confidence)}</span>}
              {draft && <span className="font-normal text-[var(--ink-soft)]"> · not yet checked</span>}
            </span>
          )}
          {basis && basis.text && <Basis label={label} basis={basis} status={tone} />}
        </div>
      )}
    </li>
  )
}

// The working behind a number, on tap: a disclosure (not a dialog; focus stays
// on the button). Escape or a tap elsewhere closes it and hands focus back.
function Basis({ label, basis, status = 'modelled' }: { label: string; basis: Basis; status?: Status }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const popId = useId()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [open])

  return (
    <span ref={root} className="inline-block">
      <span aria-hidden className="text-[var(--ink-soft)]">· </span>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={`How ${label.toLowerCase()} is worked out`}
        onClick={() => setOpen((o) => !o)}
        className="underline decoration-[var(--line)] underline-offset-[3px] hover:decoration-[var(--ink)]"
      >
        How it is worked out
      </button>
      {open && (
        <span
          id={popId}
          className="absolute inset-x-0 top-full z-[1200] mt-2 block max-w-[20rem] border-2 border-[var(--ink)] bg-white p-3 text-left text-sm leading-snug text-[var(--ink)] shadow-[4px_4px_0_var(--ink)]"
        >
          <span className="block">{basis.text}</span>
          {basis.sources.length > 0 && (
            <span className="mt-2 block text-xs text-[var(--ink-soft)]">
              Source{basis.sources.length > 1 ? 's' : ''}:{' '}
              {basis.sources.map((s, i) => (
                <span key={s.url}>{i > 0 && ' · '}<SourceLink s={s} /></span>
              ))}
            </span>
          )}
          <span className={`tag-${status} mt-2 block text-xs font-semibold`}>{STATUS_WORD[status]}: {STATUS_GLOSS[status]}.</span>
        </span>
      )}
    </span>
  )
}
