import type { Section, SectionId, Source, Status } from '../types'
import { fmtMoney } from '../pages/Home'

export const SECTION_TITLES: Record<SectionId, string> = {
  on_your_grid: 'On your grid',
  coming: 'Coming',
  your_bill: 'Your bill',
  protection: 'Protection',
  hearing: 'Hearing',
}

const STATUS_WORD: Record<Status, string> = {
  measured: 'Measured',
  reported: 'Reported',
  modelled: 'Modelled',
  unavailable: 'Not known',
}

// Every section is a document block with a status rail on the left. The rail
// colour is the status; a dashed rail means the section could not be filled.
export function SectionBlock({ id, section }: { id: SectionId; section: Section }) {
  return (
    <section id={id} className={`rail-${section.status} border-l-4 pl-5 sm:pl-7`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="text-3xl font-bold leading-none">{SECTION_TITLES[id]}</h2>
        <p className={`tag-${section.status} text-sm font-semibold`}>
          {STATUS_WORD[section.status]}
          {section.status !== 'unavailable' && (
            <span className="num font-normal text-[var(--ink-soft)]"> · confidence {Math.round(section.confidence * 100)}%</span>
          )}
        </p>
      </header>

      <p className={`mt-4 max-w-[64ch] text-lg leading-snug ${section.status === 'unavailable' ? 'text-[var(--ink-soft)]' : ''}`}>
        {section.summary}
      </p>

      {id === 'on_your_grid' && <Facilities section={section} />}
      {id === 'coming' && <Construction section={section} />}
      {id === 'your_bill' && <Bill section={section} />}
      {id === 'protection' && <Protection section={section} />}
      {id === 'hearing' && <HearingBlock section={section} />}

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

function Facilities({ section }: { section: Section }) {
  const list = section.facilities ?? []
  if (!list.length) return null
  return (
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
        {list.map((f) => (
          <tr key={f.name} className="border-b border-[var(--line)] align-top">
            <td className="py-2 pr-3">
              <span className="font-semibold">{f.name}</span>
              <span className="block text-sm text-[var(--ink-soft)]">
                {f.status.replace('_', ' ')}{f.shares_substation ? ', shares your substation' : ''}
              </span>
            </td>
            <td className="py-2 pr-3">
              {f.operator}
              {f.codename && <span className="block text-sm text-[var(--ink-soft)]">filed as {f.codename}</span>}
            </td>
            <td className="py-2 pr-3 text-right">{(f.distance_km * 0.621).toFixed(1)} mi</td>
            <td className="py-2 text-right">
              {f.estimated_mw == null ? '—' : `${f.estimated_mw} MW`}
              {f.mw_basis && <span className="block text-sm text-[var(--ink-soft)]">{f.mw_basis.replace('_', ' ')}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Construction({ section }: { section: Section }) {
  const list = section.construction ?? []
  if (!list.length) return null
  return (
    <ul className="mt-5 max-w-[72ch] divide-y divide-[var(--line)] border-y border-[var(--line)]">
      {list.map((c) => (
        <li key={c.label} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3">
          <div>
            <span className="font-semibold">{c.label}</span>
            <span className="block text-sm text-[var(--ink-soft)]">
              {(c.distance_km * 0.621).toFixed(1)} mi · {c.in_database ? 'listed in a facility database' : 'in no facility database'}
            </span>
          </div>
          <p className="num text-right">
            <span className="text-2xl font-bold">{c.footprint_acres_now.toFixed(0)} acres</span>
            <span className="block text-sm text-[var(--ink-soft)]">
              from {c.footprint_acres_then.toFixed(0)} in {c.vintages[0]} imagery, now {c.vintages[1]}
            </span>
          </p>
        </li>
      ))}
    </ul>
  )
}

function Bill({ section }: { section: Section }) {
  const p = section.price
  if (!p) return null
  const monthThen = p.rate_then * p.typical_household_kwh_month
  const monthNow = p.rate_now * p.typical_household_kwh_month
  return (
    <div className="num mt-5 max-w-[72ch]">
      <dl className="grid grid-cols-3 gap-x-4 border-y border-[var(--line)] py-3">
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">{p.window_months} months ago</dt>
          <dd className="text-xl">{(p.rate_then * 100).toFixed(1)}¢/kWh</dd>
        </div>
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">Now</dt>
          <dd className="text-xl">{(p.rate_now * 100).toFixed(1)}¢/kWh</dd>
        </div>
        <div>
          <dt className="text-sm text-[var(--ink-soft)]">Typical home, {p.typical_household_kwh_month} kWh/mo</dt>
          <dd className="text-xl font-bold">{fmtMoney(monthNow - monthThen)}/mo</dd>
        </div>
      </dl>
      {p.attribution ? (
        <p className="mt-3 text-[15px]">
          What the people who set rates say: <q>{p.attribution}</q>
        </p>
      ) : (
        <p className="mt-3 text-[15px] text-[var(--ink-soft)]">
          No regulator or market monitor statement attributes any of this change to data centres. We do not make that claim ourselves.
        </p>
      )}
    </div>
  )
}

function Protection({ section }: { section: Section }) {
  const t = section.tariff
  if (!t) return null
  const word = { in_force: 'In force', proposed: 'Proposed, not approved', none_found: 'None found', unknown: 'Not known' }[t.large_load_tariff]
  return (
    <dl className="mt-5 grid max-w-[72ch] grid-cols-2 gap-x-4 border-y border-[var(--line)] py-3 sm:grid-cols-3">
      <div>
        <dt className="text-sm text-[var(--ink-soft)]">Large-load tariff</dt>
        <dd className="text-xl">{word}</dd>
      </div>
      <div>
        <dt className="text-sm text-[var(--ink-soft)]">Shields households</dt>
        <dd className="text-xl">{t.protects_households == null ? 'Not known' : t.protects_households ? 'Yes, in part' : 'No'}</dd>
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

function HearingBlock({ section }: { section: Section }) {
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
            {h.body}{h.subject ? `: ${h.subject}` : ''}, {fmtDate(h.next_date)}
          </span>
        </p>
      )}
      {h.last_meeting_said && h.last_meeting_said.length > 0 && (
        <ul className="mt-4 space-y-3">
          {h.last_meeting_said.map((s, i) => (
            <li key={i}>
              <blockquote className="text-[17px] leading-snug">“{s.quote}”</blockquote>
              <p className="mt-1 text-sm text-[var(--ink-soft)]">
                {s.speaker_name ?? `A ${s.speaker_role}`}, {h.last_meeting_date ? fmtDate(h.last_meeting_date) : 'last meeting'}
                {s.timestamp_s != null && ` at ${fmtTime(s.timestamp_s)}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Date-only strings are local calendar dates, not UTC instants.
function localDate(d: string) {
  const [y, m, day] = d.split('-').map(Number)
  return new Date(y, m - 1, day)
}
function fmtDate(d: string) {
  return localDate(d).toLocaleDateString('en-US', { month: 'long', day: 'numeric' })
}

function fmtTime(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
