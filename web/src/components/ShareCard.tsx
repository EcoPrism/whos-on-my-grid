import type { Brief } from '../types'
import { fmtMoney, fmtRange } from '../lib/format'

// The line app/brief/headline.py::disclosure_line makes, which the PNG prints
// (app/card/spec.py builds it anew from the id, the date and the base). Used
// when the stored line has no host (no public_base_url when the brief was
// made) or predates the field. What was checked is read from the footer, as
// the API reads it; the base is this page's origin, as the API's fallback is.
function disclosure(brief: Brief): string {
  const stored = brief.card.disclosure
  if (stored?.includes('://')) return stored
  const footer = brief.card.footer ?? ''
  const drafted = footer.includes('Not verified against ground-truth data')
    ? 'Sentences drafted by Muse Spark without ground-truth data'
    : 'Facts measured from public data; sentences drafted by Muse Spark'
  const checked = footer.includes('claims not yet checked') ? 'not yet checked' : 'checked by Muse Spark Open'
  return `AI-assisted brief. ${drafted} and ${checked}. ${window.location.origin}/b/${brief.brief_id} · ${brief.generated_at.slice(0, 10)}`
}

// 1200x630, the X/OG card size, scaled to fit. The API rasterises the same
// layout (app/card/render.py); keep the two in step. The disclosure band sits
// in the pixels because platforms strip metadata; a scenario card adds the
// hypothetical band on top.
export default function ShareCard({ brief, hypothetical = false }: { brief: Brief; hypothetical?: boolean }) {
  const h = brief.headline
  return (
    <div className="flex w-full flex-col overflow-hidden" style={{ aspectRatio: '1200 / 630', containerType: 'inline-size' }}>
      {hypothetical && (
        <p className="wide shrink-0 bg-[var(--signal)] px-[4.5%] py-[0.6cqw] text-[1.8cqw] font-bold tracking-wide text-[var(--ink)]">
          HYPOTHETICAL · modelled, not measured
        </p>
      )}
      <div className="relative flex min-h-0 w-full flex-1 flex-col justify-between bg-[var(--ink)] p-[4.5%] text-[var(--paper)]">
        <div className="flex items-start justify-between gap-6">
          <p className="sign text-[9cqw] text-[var(--paper)]">{brief.card.title.replace('Who\'s on my grid: ', '')}</p>
          <p className="wide shrink-0 text-[2.6cqw] font-semibold">Who's on my grid</p>
        </div>

        <div className="flex items-end justify-between gap-6">
          <ul className="max-w-[62%] space-y-[0.8cqw] text-[2.9cqw] leading-tight">
            {brief.card.lines.filter((l) => h.ai_rent_usd_per_month === null || !/^[+−-]\$/.test(l)).map((l) => <li key={l}>{l}</li>)}
          </ul>
          {h.ai_rent_usd_per_month !== null && (
            <p className="num shrink-0 text-right">
              <span className="block text-[8.5cqw] font-extrabold leading-none text-[var(--signal)]">
                {h.ai_rent_range_usd_per_month ? fmtRange(h.ai_rent_range_usd_per_month) : `about ${fmtMoney(h.ai_rent_usd_per_month)}`}
              </span>
              <span className="block text-[2.4cqw] opacity-80">a month for a typical home, {brief.sections.your_bill.price?.as_of?.endsWith('-12') ? `${brief.sections.your_bill.price.as_of.slice(0, 4)} vs ${Number(brief.sections.your_bill.price.as_of.slice(0, 4)) - 2}` : 'vs two years ago'} · modeled</span>
            </p>
          )}
        </div>

        {brief.card.footer && (
          <p className="absolute bottom-[2%] left-[4.5%] text-[1.8cqw] opacity-60">{brief.card.footer}</p>
        )}
      </div>
      <p className="shrink-0 bg-[var(--paper)] px-[4.5%] py-[0.6cqw] text-[1.8cqw] leading-tight text-[var(--ink)]">
        {disclosure(brief)}
      </p>
    </div>
  )
}
