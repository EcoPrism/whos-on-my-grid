import { US_LOCALE, type Brief, type Locale, type Units } from '../types'

const KM_TO_MI = 0.621 // the factor the brief's tables have always used
const L_TO_GAL = 0.264172
const ACRE_TO_HA = 0.404686

// A brief's locale; older briefs carry none and are US.
export function localeOf(b: Pick<Brief, 'locale'>): Locale {
  return b.locale ?? US_LOCALE
}

// '$' for USD, so the strings stay the ones card/spec.py mirrors; the narrow
// symbol (or the code) for any other currency.
function symbol(currency: string): string {
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
