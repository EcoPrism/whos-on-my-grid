import { US_LOCALE, type ClaimSection, type Locale, type Section, type SectionId, type Source, type Status } from '../types'
import { dcNoun, fmtDate, fmtDistance, fmtMoney, fmtRate, localDate, outerWords, periodLabel as halfYears, ringWords } from '../lib/format'

export const SECTION_TITLES: Record<ClaimSection, string> = {
  on_your_grid: 'On your grid',
  coming: 'Coming',
  your_bill: 'Your bill',
  protection: 'Protection',
  hearing: 'Hearing',
  at_your_house: 'At your house',
  scenario: 'What-if',
}

const STATUS_WORD: Record<Status, string> = {
  measured: 'Measured',
  reported: 'Reported',
  modelled: 'Modeled',
  unavailable: 'Not known',
}

// While a brief streams, a section is one of: not drafted yet, a model's
// draft whose claims are unchecked, engine text from the data whose claims
// are unchecked, or final. Only a final section shows a confidence.
export type Readiness = 'pending' | 'draft' | 'engine' | 'final'

// Every section is a document block with a status rail on the left. The rail
// color is the status; a dashed rail means the section could not be filled.
// `locale` is the brief's (localeOf(brief)): it picks miles or km, the
// currency, the date order and the spelling of the engine's own words.
export function SectionBlock({ id, section, readiness = 'final', locale = US_LOCALE }: { id: SectionId; section: Section; readiness?: Readiness; locale?: Locale }) {
  const draft = readiness === 'draft' || readiness === 'pending'
  const statusWord = (s: Status) => (s === 'modelled' && locale.language !== 'en-US' ? 'Modelled' : STATUS_WORD[s])
  return (
    <section id={id} className={`rail-${section.status} border-l-4 pl-5 sm:pl-7`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="text-3xl font-bold leading-none">{SECTION_TITLES[id]}</h2>
        <p className={`${draft ? 'text-[var(--ink-soft)]' : `tag-${section.status}`} text-sm font-semibold`}>
          {readiness === 'pending' ? 'Drafting' : readiness === 'draft' ? 'Draft' : statusWord(section.status)}
          {readiness === 'final' && section.status !== 'unavailable' && (
            <span className="num font-normal text-[var(--ink-soft)]"> · confidence {Math.round(section.confidence * 100)}%</span>
          )}
          {(readiness === 'draft' || readiness === 'engine') && <span className="font-normal text-[var(--ink-soft)]"> · not yet checked</span>}
        </p>
      </header>
      {readiness === 'draft' && (
        <p className="mt-2 max-w-[64ch] text-sm text-[var(--ink-soft)]">
          Muse Spark's draft. Every claim in it is being checked against its source; the status and confidence appear when that finishes.
        </p>
      )}

      <p className={`mt-4 max-w-[64ch] text-lg leading-snug ${section.status === 'unavailable' || draft ? 'text-[var(--ink-soft)]' : ''}`}>
        {readiness === 'draft' && <span className="chip-draft">Draft</span>}
        {section.summary}
      </p>

      {id === 'on_your_grid' && <Facilities section={section} locale={locale} />}
      {id === 'coming' && <Construction section={section} locale={locale} />}
      {id === 'your_bill' && <Bill section={section} locale={locale} />}
      {id === 'protection' && <Protection section={section} />}
      {id === 'hearing' && <HearingBlock section={section} locale={locale} />}

      {section.gap && (
        <p className="hatch mt-5 max-w-[64ch] p-3 text-sm text-[var(--ink-soft)]">
          Gap: {section.gap}
        </p>
      )}

      <Footer section={section} />
    </section>
  )
}

function Footer({ section }: { section: Section }) {
  if (!section.sources.length && !section.model) return null
  return (
    <footer className="mt-5 text-sm text-[var(--ink-soft)]">
      {section.sources.length > 0 && (
        <p>
          Sources:{' '}
          {section.sources.map((s, i) => (
            <span key={s.url}>
              {i > 0 && '; '}
              <SourceLink s={s} />
            </span>
          ))}
        </p>
      )}
      {section.model && <p>Produced by {section.model}</p>}
    </footer>
  )
}

export function SourceLink({ s }: { s: Source }) {
  return (
    <a href={s.url} target="_blank" rel="noreferrer">
      {s.title}{s.page ? `, p. ${s.page}` : ''}
    </a>
  )
}

function Facilities({ section, locale }: { section: Section; locale: Locale }) {
  const list = section.facilities ?? []
  const beyond = section.beyond_ring
  if (!list.length && !beyond) return null
  return (
    <>
    {list.length > 0 && (
    <table className="num mt-5 w-full max-w-[72ch] border-collapse text-[15px]">
      <thead>
        <tr className="border-b border-[var(--ink)] text-left text-sm text-[var(--ink-soft)]">
          <th className="py-1 pr-3 font-normal">Facility</th>
          <th className="py-1 pr-3 font-normal">Operator</th>
          <th className="py-1 pr-3 text-right font-normal">Distance</th>
          <th className="py-1 text-right font-normal">Load</th>
        </tr>
      </thead>
      <tbody>
        {list.map((f, i) => (
          <tr key={`${i}-${f.name}`} className="border-b border-[var(--line)] align-top">
            <td className="py-2 pr-3">
              <span className="font-semibold">{f.name}</span>
              <span className="block text-sm text-[var(--ink-soft)]">
                {f.status === 'rejected' ? 'rejected or withdrawn' : f.status.replace('_', ' ')}{f.shares_substation ? ', likely on your substation (inferred from distance)' : ''}
              </span>
            </td>
            <td className="py-2 pr-3">
              {f.operator}
              {f.codename && <span className="block text-sm text-[var(--ink-soft)]">filed as {f.codename}</span>}
            </td>
            <td className="py-2 pr-3 text-right">{fmtDistance(f.distance_km, locale.units)}</td>
            <td className="py-2 text-right">
              {f.estimated_mw == null ? '—' : `${f.estimated_mw} MW`}
              {f.mw_basis && <span className="block text-sm text-[var(--ink-soft)]">{f.mw_basis.replace('_', ' ')}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    )}
    {beyond && (
      <p className="mt-3 max-w-[72ch] text-[15px] text-[var(--ink-soft)]">
        Beyond the {ringWords(locale.units)}, within {outerWords(locale.units)}: <span className="font-semibold text-[var(--ink)]">{beyond.name}</span>, {beyond.operator}, <span className="num">{fmtDistance(beyond.distance_km, locale.units)}</span> away. Not counted above.
      </p>
    )}
    </>
  )
}

const ACRE_TO_HA = 0.404686

// A footprint as a whole number: acres in the US, hectares elsewhere.
function footprint(acres: number, units: Locale['units'], unit = true) {
  const n = units === 'us' ? acres : acres * ACRE_TO_HA
  return `${n.toFixed(0)}${unit ? (units === 'us' ? ' acres' : ' ha') : ''}`
}

function Construction({ section, locale }: { section: Section; locale: Locale }) {
  const list = section.construction ?? []
  if (!list.length) return null
  const dc = dcNoun(locale)
  return (
    <ul className="mt-5 max-w-[72ch] divide-y divide-[var(--line)] border-y border-[var(--line)]">
      {list.map((c) => (
        <li key={c.label} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3">
          <div>
            <span className="font-semibold">{c.label}</span>
            <span className="block text-sm text-[var(--ink-soft)]">
              {fmtDistance(c.distance_km, locale.units)} · {c.kind === 'expansion' ? `expansion of a listed ${dc}` : c.in_database ? 'listed in a facility database' : c.near_cluster ? `in no facility database, adjoins a listed ${dc}` : 'in no facility database; what it is cannot be told from the air'}
            </span>
          </div>
          <p className="num text-right">
            <span className="text-2xl font-bold">{footprint(c.footprint_acres_now, locale.units)}</span>
            <span className="block text-sm text-[var(--ink-soft)]">
              from {footprint(c.footprint_acres_then, locale.units, false)} in {c.vintages[0]} imagery, now {c.vintages[1]}
            </span>
          </p>
        </li>
      ))}
    </ul>
  )
}

function Bill({ section, locale }: { section: Section; locale: Locale }) {
  const p = section.price
  if (!p) return null
  const monthThen = p.rate_then * p.typical_household_kwh_month
  const monthNow = p.rate_now * p.typical_household_kwh_month
  // A semiannual series names both half-years ("H1 2024", "H1 2026").
  const half = halfYears(p)
  const asOf = half ? null : p.as_of ? periodLabel(p.as_of) : null
  const currency = p.currency || locale.currency
  return (
    <div className="num mt-5 max-w-[72ch]">
      <dl className="grid grid-cols-3 gap-x-4 border-y border-[var(--line)] py-3">
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">{half ? half.then : asOf ? `${p.window_months} months earlier` : `${p.window_months} months ago`}</dt>
          <dd className="text-xl">{fmtRate(p.rate_then, currency)}</dd>
        </div>
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">{half ? half.now : asOf ?? 'Now'}</dt>
          <dd className="text-xl">{fmtRate(p.rate_now, currency)}</dd>
        </div>
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">Typical home, {p.typical_household_kwh_month} kWh/mo</dt>
          <dd className="text-xl font-bold">{fmtMoney(monthNow - monthThen, currency)}/mo</dd>
        </div>
      </dl>
      {p.attribution ? (
        <p className="mt-3 text-[15px]">
          What the people who set rates say: <q>{p.attribution}</q>
        </p>
      ) : locale.country === 'US' ? (
        <p className="mt-3 text-[15px] text-[var(--ink-soft)]">
          No regulator or market monitor statement attributes any of this change to data centers. We do not make that claim ourselves.
        </p>
      ) : (
        // Outside the US the engine searches no regulator statements, so it
        // says only what it does itself.
        <p className="mt-3 text-[15px] text-[var(--ink-soft)]">
          This brief does not attribute any of this change to {dcNoun(locale)}s.
        </p>
      )}
    </div>
  )
}

function Protection({ section }: { section: Section }) {
  const t = section.tariff
  if (!t) return null
  const word = { in_force: 'In force', proposed: 'Proposed, not approved', none_found: 'None found', unknown: 'Not known' }[t.large_load_tariff]
  // A connection policy is not a tariff, and "No" there is about its stated
  // aim (keeping build-out costs off households is not it), not a finding
  // about bills.
  const policy = t.kind === 'connection_policy'
  const shields = t.protects_households == null ? 'Not known' : t.protects_households ? 'Yes, in part' : policy ? 'No (not its stated aim)' : 'No'
  return (
    <dl className="mt-5 grid max-w-[72ch] grid-cols-2 gap-x-4 border-y border-[var(--line)] py-3 sm:grid-cols-3">
      <div>
        <dt className="text-sm text-[var(--ink-soft)]">{policy ? 'Connection policy' : 'Large-load tariff'}</dt>
        <dd className="text-xl">{word}</dd>
      </div>
      <div>
        <dt className="text-sm text-[var(--ink-soft)]">Shields households</dt>
        <dd className="text-xl">{shields}</dd>
      </div>
      {(t.name || t.docket) && (
        <div className="col-span-2 sm:col-span-1">
          <dt className="text-sm text-[var(--ink-soft)]">Where it says so</dt>
          <dd className="text-xl">{t.name ?? '—'}{t.docket ? <span className="block text-sm text-[var(--ink-soft)]">docket {t.docket}</span> : null}</dd>
        </div>
      )}
    </dl>
  )
}

function HearingBlock({ section, locale }: { section: Section; locale: Locale }) {
  const h = section.hearing
  if (!h || (!h.next_date && !h.last_meeting_said?.length)) return null
  const days = h.next_date ? Math.ceil((localDate(h.next_date).getTime() - Date.now()) / 86_400_000) : null
  return (
    <div className="mt-5 max-w-[72ch]">
      {h.next_date && (
        <p className="num border-y border-[var(--line)] py-3">
          <span className="text-2xl font-bold">
            {days !== null && days >= 0 ? `${days} day${days === 1 ? '' : 's'}` : 'Passed'}
          </span>
          <span className="block text-sm text-[var(--ink-soft)]">
            {h.body}{h.subject ? `: ${h.subject}` : ''}, {fmtDate(h.next_date, locale.language)}
          </span>
        </p>
      )}
      {h.last_meeting_said && h.last_meeting_said.length > 0 && (
        <ul className="mt-4 space-y-3">
          {h.last_meeting_said.map((s, i) => (
            <li key={i}>
              <blockquote className="text-[17px] leading-snug">“{s.quote}”</blockquote>
              <p className="mt-1 text-sm text-[var(--ink-soft)]">
                {s.speaker_name ?? `A ${s.speaker_role}`}, {h.last_meeting_date ? fmtDate(h.last_meeting_date, locale.language) : 'last meeting'}
                {s.timestamp_s != null && ` at ${fmtTime(s.timestamp_s)}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// "2024-12" -> "Calendar 2024"; "2026-08" -> "12 months to Aug 2026".
function periodLabel(asOf: string) {
  const [y, m] = asOf.split('-').map(Number)
  if (m === 12) return `Calendar ${y}`
  return `12 months to ${new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}`
}


function fmtTime(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
