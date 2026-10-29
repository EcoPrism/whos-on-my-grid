import { useEffect, useState } from 'react'
import { basisOf, numberOf } from '../lib/glance'
import { useAnimatedNumber, usePrefersReducedMotion } from '../lib/motion'
import { STATUS_WORD, TOPIC_WORD } from '../lib/words'
import type { Glance, GlanceItem, GlanceTopic } from '../types'
import { Counter } from './ImpactCounters'

const COUNT_MS = 900
// The concerns in the order people feel them. Air only when something was written.
const ORDER: GlanceTopic[] = ['bill', 'grid', 'noise', 'water', 'land', 'taxes', 'air']

// The brief at a glance: one tile per concern, each with the number the
// engine has (a bill range, a count, a distance, acres), the sentence a model
// wrote, or Not public with who to ask. While the brief streams, a tile whose
// entry has not arrived yet breathes.
export default function GlanceTiles({ glance, checking = false }: { glance?: Glance; checking?: boolean }) {
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const ready = shown || reduced
  // A brief made before the tiles existed has no glance block; the engine
  // fingerprint regenerates it on the next request, so the page shows nothing
  // rather than six empty tiles. While a brief streams, the tiles fill in.
  if (!glance && !checking) return null
  const topics = ORDER.filter((t) => t !== 'air' || (glance?.air && glance.air.status !== 'unavailable'))
  return (
    <section aria-label="The brief at a glance" className="mx-auto mt-6 max-w-6xl px-4">
      <ul className="grid gap-x-5 gap-y-7 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {topics.map((t) => {
          const item = glance?.[t]
          return item ? (
            <Tile key={t} topic={t} item={item} ready={ready} checking={checking} />
          ) : (
            <li key={t} className="tile tile-unavailable breathe pt-3">
              <h3 className="text-sm font-semibold leading-tight text-[var(--ink-soft)]">{TOPIC_WORD[t]}</h3>
              <p className="wide num mt-2 text-[clamp(2rem,5vw,2.75rem)] font-bold leading-none tracking-tight text-[var(--line)]" aria-hidden>—</p>
              <p className="sr-only">Still being written</p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Tile({ topic, item, ready, checking }: { topic: GlanceTopic; item: GlanceItem; ready: boolean; checking: boolean }) {
  // A plain number ticks up from zero on first paint; a range or a word is shown as is.
  const num = numberOf(item.value)
  const n = useAnimatedNumber(ready && num ? num.n : 0, COUNT_MS)
  const value = num ? `${fmt(n, num.n)}${num.unit}` : item.value
  // A model's sentence is a draft until the check ends; the engine's numbers are final.
  const draft = checking && item.status === 'reported'
  return (
    <Counter
      label={TOPIC_WORD[topic]}
      status={item.status}
      value={value}
      final={item.value ?? (item.text ? null : STATUS_WORD[item.status])}
      text={item.value ? undefined : item.text ?? undefined}
      sub={item.sub ?? undefined}
      unknown={item.status === 'unavailable'}
      confidence={item.confidence}
      draft={draft}
      size="small"
      basis={item.text && item.value ? basisOf(item) : item.sources.length ? basisOf(item) : undefined}
    />
  )
}

// Keep the decimals the final value has, so "0.5" never ticks as "0.49".
function fmt(n: number, final: number): string {
  const decimals = Number.isInteger(final) ? 0 : Math.min(2, (String(final).split('.')[1] ?? '').length)
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}
