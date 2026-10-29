import { useEffect, useId, useRef, useState } from 'react'
import { usePrefersReducedMotion } from '../lib/motion'
import { STATUS_WORD } from '../lib/words'
import type { Impact } from '../types'
import { fmtAcres, fmtNice, fmtUsd } from '../lib/format'

// Where each stage sits on the 0–100 scrubber. Only the build itself has a
// duration the engine cites (construction_months); the stretch from
// announcement to permit varies too much to put months on it, so the scale
// is stages, and months are named only inside construction.
const PERMITTED = 20
const BUILD_START = 35
// The last stretch before energised: load comes on, so power, water and the
// bill climb to their final values exactly at the energised mark.
const COMMISSION = 85
const ENERGISED = 100

const STAGES = [
  { at: 0, label: 'Announced' },
  { at: PERMITTED, label: 'Permitted' },
  { at: BUILD_START, label: 'Under construction' },
  { at: ENERGISED, label: 'Energised' },
] as const

const PLAY_MS = 4500

function ramp(t: number, from: number, to: number): number {
  return Math.min(1, Math.max(0, (t - from) / (to - from)))
}

function stageAt(t: number): string {
  if (t >= ENERGISED) return 'Energised'
  if (t >= BUILD_START) return 'Under construction'
  if (t >= PERMITTED) return 'Permitted'
  return 'Announced'
}

type Props = {
  months: [number, number] | null
  impact: Impact
}

// From announcement to energised, in four stages. Dragging the scrubber fills
// the bars: land as the site is cleared and built, power, water and the bill
// as the campus comes on. All client-side arithmetic over the engine's final
// values; it plays once on arrival, and under reduced motion it starts at the end.
export default function Timeline({ months, impact }: Props) {
  const reduced = usePrefersReducedMotion()
  const [rawT, setT] = useState(reduced ? ENERGISED : 0)
  const [rawPlaying, setPlaying] = useState(!reduced)
  // Reduced motion: no playback, and the bars sit at their final values.
  const playing = rawPlaying && !reduced
  const t = reduced && rawPlaying ? ENERGISED : rawT
  // While the scrubber has focus its aria-valuetext speaks; the live stage line stays quiet.
  const [scrubbing, setScrubbing] = useState(false)
  const raf = useRef(0)
  // Read once, at the moment play starts.
  const tNow = useRef(t)
  useEffect(() => { tNow.current = t })
  const id = useId()
  const inputId = `${id}-scrub`
  const ticksId = `${id}-ticks`

  useEffect(() => {
    if (!playing) return
    const from = tNow.current >= ENERGISED ? 0 : tNow.current
    const start = performance.now() - (from / ENERGISED) * PLAY_MS
    const tick = (now: number) => {
      const v = Math.min(ENERGISED, ((now - start) / PLAY_MS) * ENERGISED)
      setT(v)
      if (v < ENERGISED) raf.current = requestAnimationFrame(tick)
      else setPlaying(false)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing])

  const land = ramp(t, BUILD_START, ENERGISED)
  const load = ramp(t, COMMISSION, ENERGISED)
  const stage = stageAt(t)

  let when = stage
  if (stage === 'Under construction' && months) {
    const f = ramp(t, BUILD_START, ENERGISED)
    const lo = Math.max(1, Math.round(f * months[0]))
    const hi = Math.max(1, Math.round(f * months[1]))
    when = `${stage}, month ${lo === hi ? lo : `${lo}–${hi}`} of ${months[0]}–${months[1]}`
  }

  const { power, water, bill } = impact
  const range = bill.range_usd_per_month
  const bars: { key: string; label: string; fill: number; value: string | null; note?: string }[] = [
    {
      key: 'power',
      label: 'Electricity',
      fill: load,
      value: power?.homes_equivalent != null ? `${fmtNice(power.homes_equivalent * load)} homes’ worth` : null,
    },
    {
      key: 'water',
      label: 'Water',
      fill: water && water.gal_per_day > 0 ? load : 0,
      value: water ? `${fmtNice(water.gal_per_day * load)} gal a day` : null,
    },
    {
      key: 'land',
      label: 'Land',
      fill: land,
      value: impact.land ? `${fmtAcres(impact.land.acres * land)} acres` : null,
    },
    {
      key: 'bill',
      label: 'Electric bill',
      fill: range ? load : 0,
      value: range
        ? `+${fmtUsd(range[0] * load)} to ${fmtUsd(range[1] * load)} a month`
        : bill.kind === 'shielded' ? 'Shielded' : bill.kind === 'partial' ? 'Partly shielded' : null,
    },
  ]

  const stageButton = (s: (typeof STAGES)[number]) => (
    <button
      type="button"
      onClick={() => { setPlaying(false); setT(s.at) }}
      aria-current={stage === s.label ? 'step' : undefined}
      className={`leading-tight ${stage === s.label ? 'font-bold text-[var(--ink)]' : 'text-[var(--ink-soft)]'}`}
    >
      {s.label}
    </button>
  )

  return (
    <section aria-labelledby={`${id}-head`}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id={`${id}-head`} className="wide text-xs font-semibold uppercase tracking-wide text-[var(--ink-soft)]">
          From announcement to energised
        </h2>
        <span className="tag-modelled text-xs font-semibold">{STATUS_WORD.modelled}</span>
      </div>

      <div className="mt-3 flex items-start gap-3">
        <button
          type="button"
          onClick={() => {
            // Reduced motion: no playback, so the button jumps between the ends.
            if (reduced) {
              setPlaying(false)
              setT(t >= ENERGISED ? 0 : ENERGISED)
            } else setPlaying((p) => !p)
          }}
          className="chip shrink-0"
        >
          {reduced
            ? t >= ENERGISED ? 'Back to start' : 'Jump to energised'
            : playing ? 'Pause' : t >= ENERGISED ? 'Replay' : 'Play'}
        </button>
        <div className="min-w-0 flex-1">
        <label htmlFor={inputId} className="sr-only">Stage, from announced to energised</label>
        <input
          id={inputId}
          type="range"
          min={0}
          max={100}
          step={1}
          list={ticksId}
          value={Math.round(t)}
          aria-valuetext={when}
          onFocus={() => setScrubbing(true)}
          onBlur={() => setScrubbing(false)}
          onChange={(e) => {
            setPlaying(false)
            setT(Number(e.target.value))
          }}
          className="timeline-range w-full"
        />
        <datalist id={ticksId}>
          {STAGES.map((s) => <option key={s.label} value={s.at} label={s.label} />)}
        </datalist>

        {/* Stage names under the track, each one a shortcut to its mark. They
            sit in the track's own column so a name lines up with its mark; on
            a phone the marks are too close for names to fit there, so they
            spread out in a row instead. */}
        <ol className="mt-1 flex justify-between gap-2 text-xs sm:hidden" aria-label="Stages">
          {STAGES.map((s) => (
            <li key={s.label} className={s.at === ENERGISED ? 'text-right' : ''}>
              {stageButton(s)}
            </li>
          ))}
        </ol>
        <ol className="relative mt-1 hidden h-6 text-xs sm:block" aria-label="Stages">
          {STAGES.map((s) => (
            <li
              key={s.label}
              className="absolute top-0 whitespace-nowrap"
              style={s.at === 0 ? { left: 0 } : s.at === ENERGISED ? { right: 0 } : { left: `${s.at}%`, transform: 'translateX(-50%)' }}
            >
              {stageButton(s)}
            </li>
          ))}
        </ol>
        </div>
      </div>

      {/* The month detail changes every frame while playing, so it is not a
          live region; only the stage is announced, and only when playback is
          not running (the range's aria-valuetext gives the month on each step). */}
      <p className="mt-3 text-sm font-semibold" aria-hidden="true">{when}</p>
      <p className="sr-only" aria-live="polite">{playing || scrubbing ? '' : stage}</p>
      {months && (
        <p className="text-sm text-[var(--ink-soft)]">
          Building takes about <span className="num">{months[0]}–{months[1]}</span> months once permitted; the stretch
          before that varies too much to put a number on.
        </p>
      )}

      <dl className="mt-4 grid gap-3">
        {bars.map((b) => (
          <div key={b.key} className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-x-3 sm:grid-cols-[7rem_minmax(0,1fr)_14rem]">
            <dt className="text-sm font-semibold">{b.label}</dt>
            <dd className="contents">
              <span
                className={`impact-bar block h-3 ${b.value === null ? 'hatch' : ''}`}
                role="presentation"
              >
                {b.value !== null && <span className="impact-bar-fill block h-full" style={{ width: `${b.fill * 100}%` }} />}
              </span>
              <span className="num col-start-2 text-sm text-[var(--ink-soft)] sm:col-start-auto">
                {b.value ?? STATUS_WORD.unavailable}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
