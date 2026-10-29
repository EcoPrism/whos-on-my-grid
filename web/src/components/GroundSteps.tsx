import type { GroundStep, StepState } from '../lib/api'
import type { Steps } from '../lib/live'

// The ground steps as the engine reports them while a brief is made: what it
// is fetching, in plain names, ticked as each lands. A step with nothing to
// find is shown soft, a failed one in the contradicted colour.
export const STEP_WORD: Record<GroundStep, string> = {
  facilities: 'data centers',
  utility: 'your utility',
  prices: 'prices',
  tariff: 'tariff',
  imagery: 'aerial photos',
  hearings: 'hearings',
}

const ORDER: GroundStep[] = ['facilities', 'utility', 'prices', 'tariff', 'imagery', 'hearings']

function mark(state: StepState | undefined): { glyph: string; cls: string; word: string } {
  switch (state) {
    case 'ok':
      return { glyph: '✓', cls: 'text-[var(--ink)]', word: 'found' }
    case 'none':
      return { glyph: '–', cls: 'text-[var(--ink-soft)]', word: 'none' }
    case 'failed':
      return { glyph: '✕', cls: 'text-[var(--contradicted)]', word: 'could not be read' }
    default:
      return { glyph: '·', cls: 'breathe text-[var(--ink-soft)]', word: 'fetching' }
  }
}

export default function GroundSteps({ steps }: { steps: Steps }) {
  return (
    <span className="inline-flex flex-wrap gap-x-3 gap-y-1">
      {ORDER.map((k) => {
        const m = mark(steps[k])
        return (
          <span key={k} className={`inline-flex items-center gap-1 ${m.cls}`}>
            <span aria-hidden className="num w-3 text-center font-semibold">{m.glyph}</span>
            <span className="sr-only">{m.word}: </span>
            {STEP_WORD[k]}
          </span>
        )
      })}
    </span>
  )
}

export function allLanded(steps: Steps): boolean {
  return ORDER.every((k) => steps[k] !== undefined)
}
