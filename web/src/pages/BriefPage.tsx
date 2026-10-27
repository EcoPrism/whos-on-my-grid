import { Link, useParams } from 'react-router-dom'
import { getBrief } from '../lib/briefs'
import MapView from '../components/MapView'
import { SectionBlock } from '../components/Sections'
import Claims from '../components/Claims'
import ShareCard from '../components/ShareCard'
import type { SectionId } from '../types'
import { fmtMoney } from './Home'

const ORDER: SectionId[] = ['on_your_grid', 'coming', 'your_bill', 'protection', 'hearing']

export default function BriefPage() {
  const { key = '' } = useParams()
  const brief = getBrief(key)

  if (!brief) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-24">
        <h1 className="sign text-5xl">No brief for that address</h1>
        <p className="mt-6">The app is running on fixtures. <Link to="/">Pick one of the example addresses.</Link></p>
      </main>
    )
  }

  const a = brief.address
  const h = brief.headline
  const counts = countStatuses(brief)

  return (
    <main className="pb-24">
      <nav className="mx-auto flex max-w-5xl items-baseline justify-between px-4 pt-5 text-sm">
        <Link to="/" className="no-underline"><span className="wide font-semibold">Who's on my grid</span></Link>
        {brief.fixture && <span className="text-[var(--ink-soft)]">Fixture. Operators and sources are fictional.</span>}
      </nav>

      <header className="mx-auto max-w-5xl px-4 pt-10">
        <p className="text-[var(--ink-soft)]">{a.county ? `${a.county} County, ` : ''}{a.state}{a.utility ? ` · served by ${a.utility}` : ''}</p>
        <h1 className="sign mt-1 text-[clamp(2.6rem,8vw,6rem)]">{a.display}</h1>
        {h.one_liner && <p className="mt-6 max-w-[58ch] text-xl leading-snug">{h.one_liner}</p>}
        <p className="mt-4 text-sm text-[var(--ink-soft)]">
          {counts.measured} measured · {counts.reported} reported · {counts.modelled} modelled · {counts.unavailable} not known
        </p>
      </header>

      <div className="mx-auto mt-8 max-w-5xl sm:px-4">
        <MapView brief={brief} />
        <p className="px-4 pt-2 text-sm text-[var(--ink-soft)] sm:px-0">
          Dashed ring: five miles. Dots: facilities (solid live, amber under construction, hollow announced). Green outlines: footprints measured from aerial imagery.
        </p>
      </div>

      <div className="mx-auto mt-14 max-w-5xl space-y-14 px-4">
        {ORDER.map((id) => <SectionBlock key={id} id={id} section={brief.sections[id]} />)}
        <Claims claims={brief.claims} />

        <section id="card" className="border-t-2 border-[var(--ink)] pt-6">
          <h2 className="text-3xl font-bold leading-none">Share it</h2>
          <p className="mt-3 max-w-[64ch] text-[15px] text-[var(--ink-soft)]">
            The card carries the sources line so the number never travels without them.
            {h.percentile !== null && h.ai_rent_usd_per_month !== null && ` ${fmtMoney(h.ai_rent_usd_per_month)} a month puts this address above ${h.percentile}% of US households, weighted by state population.`}
          </p>
          <div className="mt-5 max-w-3xl"><ShareCard brief={brief} /></div>
        </section>

        <p className="text-sm text-[var(--ink-soft)]">
          Brief {brief.brief_id}, generated {new Date(brief.generated_at).toLocaleString('en-US')}, mode {brief.source_mode}. The address is not stored; the id is a hash of it.
        </p>
      </div>
    </main>
  )
}

function countStatuses(brief: ReturnType<typeof getBrief> & object) {
  const c = { measured: 0, reported: 0, modelled: 0, unavailable: 0 }
  for (const id of ORDER) c[brief.sections[id].status]++
  return c
}
