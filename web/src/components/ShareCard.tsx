import type { Brief } from '../types'
import { fmtMoney, fmtRange } from '../pages/Home'

// 1200x630, the X/OG card size, scaled to fit. Rendered in the DOM for now;
// an image endpoint will rasterise the same markup later.
export default function ShareCard({ brief }: { brief: Brief }) {
  const h = brief.headline
  return (
    <div className="w-full overflow-hidden" style={{ aspectRatio: '1200 / 630' }}>
      <div
        className="relative flex h-full w-full flex-col justify-between bg-[var(--ink)] p-[4.5%] text-[var(--paper)]"
        style={{ containerType: 'inline-size' }}
      >
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
              <span className="block text-[2.4cqw] opacity-80">a month for a typical home, vs two years ago · modeled</span>
            </p>
          )}
        </div>

        {brief.card.footer && (
          <p className="absolute bottom-[2%] left-[4.5%] text-[1.8cqw] opacity-60">{brief.card.footer}</p>
        )}
      </div>
    </div>
  )
}
