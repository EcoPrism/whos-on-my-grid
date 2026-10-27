import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fixtures, resolveAddress } from '../lib/briefs'

export default function Home() {
  const [input, setInput] = useState('')
  const [miss, setMiss] = useState(false)
  const nav = useNavigate()

  function go(e: React.FormEvent) {
    e.preventDefault()
    const key = resolveAddress(input)
    if (key) nav(`/b/${key}`)
    else setMiss(true)
  }

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-14 sm:pt-24">
      <h1 className="sign text-[clamp(3.2rem,12vw,7.5rem)]">
        Who's on<br />my grid?
      </h1>
      <p className="mt-8 max-w-[52ch] text-xl leading-snug">
        Type a US address. Find out which data centres share your local grid, what is being built
        near you, what your bill has done, and when the next vote is.
      </p>

      <form onSubmit={go} className="mt-10">
        <label htmlFor="address" className="block text-sm text-[var(--ink-soft)]">
          Street address, city, state
        </label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            id="address"
            value={input}
            onChange={(e) => { setInput(e.target.value); setMiss(false) }}
            placeholder="21715 Filigree Ct, Ashburn, VA"
            autoComplete="street-address"
            className="w-full border-2 border-[var(--ink)] bg-white px-4 py-3 text-lg placeholder:text-[var(--line)]"
          />
          <button
            type="submit"
            className="shrink-0 border-2 border-[var(--ink)] bg-[var(--ink)] px-6 py-3 text-lg font-semibold text-[var(--paper)]"
          >
            Check my grid
          </button>
        </div>
        {miss && (
          <p className="mt-3 text-sm" role="alert">
            Only the five example addresses below work while the app runs on fixtures. Pick one of them.
          </p>
        )}
      </form>

      <section className="mt-14">
        <h2 className="text-sm text-[var(--ink-soft)]">Example addresses</h2>
        <ul className="mt-3 divide-y divide-[var(--line)] border-y border-[var(--line)]">
          {Object.entries(fixtures).map(([key, b]) => (
            <li key={key}>
              <a href={`/b/${key}`} className="flex items-baseline justify-between gap-4 py-3 no-underline hover:bg-white">
                <span className="font-semibold">{b.address.display}</span>
                <span className="num shrink-0 text-sm text-[var(--ink-soft)]">
                  {b.headline.ai_rent_usd_per_month === null ? 'bill: not known' : `${fmtMoney(b.headline.ai_rent_usd_per_month)}/mo`}
                </span>
              </a>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-[var(--ink-soft)]">
          Every operator, source and quote in these examples is fictional. They exist to build the page against.
        </p>
      </section>
    </main>
  )
}

export function fmtMoney(n: number) {
  const sign = n < 0 ? '−' : '+'
  return `${sign}$${Math.abs(n).toFixed(0)}`
}
