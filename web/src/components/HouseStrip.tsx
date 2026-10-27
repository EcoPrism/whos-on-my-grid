import type { HouseLine, Status } from '../types'
import { SourceLink } from './Sections'

const STATUS_WORD: Record<Status, string> = {
  measured: 'Measured',
  reported: 'Reported',
  modelled: 'Modeled',
  unavailable: 'Not known',
}

// "What this means at your house": three or four plain sentences under the
// hero, the thing a resident screenshots for a neighbor. A layer over the five
// sections, not a sixth. Every sentence still carries its status, confidence
// and sources, in small type so the sentence stays the point.
export default function HouseStrip({ lines }: { lines: HouseLine[] }) {
  if (!lines.length) return null
  return (
    <section aria-label="What this means at your house" className="border-y-2 border-[var(--ink)] bg-white">
      <div className="mx-auto max-w-6xl px-4 py-4 sm:py-5">
        <h2 className="wide text-xs font-semibold uppercase tracking-wide text-[var(--ink-soft)]">What this means at your house</h2>
        <ol className="mt-2 grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {lines.map((l, i) => (
            <li key={i} className={`rail-${l.status} border-l-4 pl-3`}>
              <p className="text-[17px] leading-snug">{l.text}</p>
              <p className="mt-1 text-xs text-[var(--ink-soft)]">
                <span className={`tag-${l.status} font-semibold`}>{STATUS_WORD[l.status]}</span>
                {l.status !== 'unavailable' && <span className="num"> · {Math.round(l.confidence * 100)}%</span>}
                {l.sources.map((s) => (
                  <span key={s.url}> · <SourceLink s={s} /></span>
                ))}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
