import { US_LOCALE, type Brief, type Locale, type Price, type Units } from '../types'

const KM_TO_MI = 0.621 // the factor the brief's tables have always used
const L_TO_GAL = 0.264172
const ACRE_TO_HA = 0.404686

// A brief's locale; older briefs carry none and are US.
export function localeOf(b: Pick<Brief, 'locale'>): Locale {
  return b.locale ?? US_LOCALE
}

// '$' for USD, so the strings stay the ones card/spec.py mirrors; the narrow
// symbol (or the code) for any other currency.
export function symbol(currency: string): string {
  if (currency === 'USD') return '$'
  try {
    const parts = new Intl.NumberFormat('en', { style: 'currency', currency, currencyDisplay: 'narrowSymbol' }).formatToParts(0)
    return parts.find((p) => p.type === 'currency')?.value ?? `${currency} `
  } catch {
    return `${currency} `
  }
}

export function fmtMoney(n: number, currency = 'USD') {
  const sign = n < 0 ? '−' : '+'
  return `${sign}${symbol(currency)}${Math.abs(n).toFixed(0)}`
}

// An amount with no sign, whole units: "$12", "€45".
export function fmtMoneyAbs(n: number, currency = 'USD') {
  return `${symbol(currency)}${Math.abs(n).toFixed(0)}`
}

// A price per kWh: US cents as the brief has always shown them ("13.2¢/kWh");
// any other currency in its own units, to the four places Eurostat reports
// ("€0.3871/kWh"), so the figure reads as the cited page prints it.
export function fmtRate(rate: number, currency = 'USD') {
  return currency === 'USD' ? `${(rate * 100).toFixed(1)}¢/kWh` : `${symbol(currency)}${rate.toFixed(4)}/kWh`
}

// A date-only string ("2026-11-04") is a local calendar date, not a UTC instant.
export function localDate(d: string) {
  const [y, m, day] = d.split('-').map(Number)
  return new Date(y, m - 1, day)
}

// "November 4" in the US, "4 November" in Ireland.
export function fmtDate(d: string, language = 'en-US') {
  return localDate(d).toLocaleDateString(language, { month: 'long', day: 'numeric' })
}

// The brief's ring, as a noun phrase: "five-mile ring" or "8 km ring".
export function ringWords(units: Units = 'us') {
  return units === 'us' ? 'five-mile ring' : '8 km ring'
}

// The ring's radius in words: "five miles" or "8 km".
export function ringRadius(units: Units = 'us') {
  return units === 'us' ? 'five miles' : '8 km'
}

// The outer limit for the nearest campus past the ring: ten miles, or 16 km.
export function outerWords(units: Units = 'us') {
  return units === 'us' ? 'ten' : '16 km'
}

// The "close by" count: within a mile, or within a kilometre.
export function nearKm(units: Units = 'us') {
  return units === 'us' ? 1.61 : 1
}
export function nearWords(units: Units = 'us') {
  return units === 'us' ? 'within a mile' : 'within a kilometre'
}

// The spelling the brief's own text uses for its subject.
export function dcNoun(locale: Locale) {
  return locale.language === 'en-US' ? 'data center' : 'data centre'
}

// A semiannual series' period words: as_of month 06 is H1, 12 is H2, and
// "then" is as_of minus window_months ("H1 2026 vs H1 2024"). Null for any
// other granularity, whose labels each caller already words.
export function periodLabel(price: Pick<Price, 'as_of' | 'window_months' | 'granularity'> | undefined | null): { now: string; then: string; both: string } | null {
  if (!price || price.granularity !== 'semiannual' || !price.as_of) return null
  const [y, m] = price.as_of.split('-').map(Number)
  if (!y || (m !== 6 && m !== 12)) return null
  const half = (year: number, month: number) => `${month <= 6 ? 'H1' : 'H2'} ${year}`
  const months = y * 12 + (m - 1) - (price.window_months ?? 24)
  const now = half(y, m)
  const then = half(Math.floor(months / 12), (months % 12) + 1)
  return { now, then, both: `${now} vs ${then}` }
}

export function fmtDistance(km: number, units: Units = 'us'): string {
  return units === 'us' ? `${(km * KM_TO_MI).toFixed(1)} mi` : `${km.toFixed(1)} km`
}

export function fmtVolume(litres: number, units: Units = 'us'): string {
  return units === 'us' ? `${fmtNice(litres * L_TO_GAL)} gallons` : `${fmtNice(litres)} litres`
}

export function fmtArea(acres: number, units: Units = 'us'): string {
  return units === 'us' ? `${fmtAcres(acres)} acres` : `${fmtAcres(acres * ACRE_TO_HA)} hectares`
}

// A count as people say it: 64,900 not 64,893; 7,800 not 7,812. One rounding
// for every modelled count on the what-if page, so the slider label and the
// counters never show the same figure two ways.
export function fmtNice(n: number): string {
  const a = Math.abs(n)
  const step = a >= 10_000 ? 100 : a >= 1000 ? 10 : 1
  return (Math.round(n / step) * step).toLocaleString('en-US')
}

// Dollars a month: cents when the amount is under $10, whole dollars above.
export function fmtUsd(n: number): string {
  const a = Math.abs(n)
  return a < 10 ? `$${a.toFixed(2)}` : `$${Math.round(a).toLocaleString('en-US')}`
}

export function fmtAcres(n: number): string {
  return n < 10 ? n.toFixed(1) : Math.round(n).toLocaleString('en-US')
}

// The modeled bill change is shown as a range, never as a point estimate alone.
export function fmtRange([lo, hi]: [number, number], currency = 'USD') {
  const sign = hi < 0 ? '−' : '+'
  const s = symbol(currency)
  return `${sign}${s}${Math.abs(lo).toFixed(0)} to ${s}${Math.abs(hi).toFixed(0)}`
}
