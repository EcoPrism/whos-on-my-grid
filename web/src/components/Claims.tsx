import type { Claim, Verdict } from '../types'
import { SECTION_TITLES, SourceLink } from './Sections'

const MARK: Record<Verdict, { glyph: string; word: string; cls: string }> = {
  supported: { glyph: '✓', word: 'Supported', cls: 'text-[var(--measured)]' },
  contradicted: { glyph: '✕', word: 'Contradicted', cls: 'text-[var(--contradicted)]' },
  unverifiable: { glyph: '?', word: 'Could not verify', cls: 'text-[var(--modelled)]' },
  unchecked: { glyph: '·', word: 'Not checked', cls: 'text-[var(--unavailable)]' },
}

// The appendix. Each claim: what was said, the quote it rests on, and what the
// second model made of it. Disagreements are shown, not hidden.
export default function Claims({ claims }: { claims: Claim[] }) {
  if (!claims.length) return null
  const verifier = claims.find((c) => c.verified_by)?.verified_by
  return (
    <section id="claims" className="border-t-2 border-[var(--ink)] pt-6">
      <h2 className="text-3xl font-bold leading-none">Every claim, checked</h2>
      <p className="mt-3 max-w-[64ch] text-[15px] text-[var(--ink-soft)]">
        Each claim rests on a verbatim quote from its source.{' '}
        {verifier ? `A second, independent model (${verifier}) re-read each source and gave a verdict.` : 'No verifier has run on this brief yet.'}
      </p>
      <ol className="mt-5 divide-y divide-[var(--line)] border-y border-[var(--line)]">
        {claims.map((c) => {
          const m = MARK[c.verdict]
          return (
            <li key={c.id} className="grid grid-cols-[2rem_1fr] gap-x-3 py-3">
              <span className={`${m.cls} text-xl font-bold leading-none`} aria-label={m.word}>{m.glyph}</span>
              <div className="max-w-[64ch]">
                <p>{c.text}</p>
                <p className="mt-1 text-sm text-[var(--ink-soft)]">
                  {SECTION_TITLES[c.section]} · <SourceLink s={c.source} />
                  {c.source.quote && <> · <q>{c.source.quote}</q></>}
                </p>
                {c.verifier_note && <p className={`mt-1 text-sm ${m.cls}`}>{m.word}: {c.verifier_note}</p>}
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
