import { useEffect, useId, useRef, useState } from 'react'
import { fmtAcres, fmtNice, fmtUsd } from '../lib/format'
import { useAnimatedNumber, usePrefersReducedMotion } from '../lib/motion'
import type { HouseLine, HouseTopic, Impact } from '../types'
import { SourceLink } from './Sections'

const COUNT_MS = 900

// The basis (the working) for a counter: the impact block's own, or the
// matching strip line's, with that line's sources.
function basisFor(block: { basis?: string } | null | undefined, topic: HouseTopic, lines: HouseLine[] | undefined) {
  const line = lines?.find((l) => l.topic === topic)
  const text = block?.basis ?? (line && 'basis' in line ? String((line as { basis?: unknown }).basis ?? '') : '')
  return { text: text || line?.text || '', sources: line?.sources ?? [] }
}

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

type CounterProps = {
  label: string
  value: string | null // what is on screen now (animating); null when not known
  final: string | null // the settled value, for screen readers
  sub?: string
  unknown?: boolean // a word stands in for the number ("Unknown"): tagged not known
  basis: { text: string; sources: HouseLine['sources'] }
}

function Counter({ label, value, final, sub, unknown = false, basis }: CounterProps) {
  const known = value !== null && !unknown
  return (
    <li className={`tile ${known ? 'tile-modelled' : 'tile-unavailable'} pt-3`}>
      <h3 className="text-sm font-semibold leading-tight text-[var(--ink-soft)]">{label}</h3>
      {/* The ticking number is hidden from screen readers; they get the final one. */}
      <p className="wide num mt-2 text-[clamp(2rem,5vw,2.75rem)] font-bold leading-none tracking-tight" aria-hidden>
        {value ?? '—'}
      </p>
      <p className="sr-only">{value !== null ? final : 'Not known'}</p>
      {sub && <p className="mt-2 text-sm leading-snug text-[var(--ink-soft)]">{sub}</p>}
      {/* relative: the working's popover is anchored to this row, so it is never wider than the tile. */}
      <div className="relative mt-2 flex flex-wrap items-center gap-x-2 text-xs">
        <span className={`${known ? 'tag-modelled' : 'tag-unavailable'} font-semibold`}>{known ? 'Modeled' : 'Not known'}</span>
        {basis.text && <Basis label={label} basis={basis} />}
      </div>
    </li>
  )
}

// The working behind a number, on tap: a disclosure (not a dialog; focus stays
// on the button). Escape or a tap elsewhere closes it and hands focus back.
function Basis({ label, basis }: { label: string; basis: CounterProps['basis'] }) {
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
          <span className="tag-modelled mt-2 block text-xs font-semibold">Modeled: the engine’s arithmetic over cited figures, not a measurement.</span>
        </span>
      )}
    </span>
  )
}
