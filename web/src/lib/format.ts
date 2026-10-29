export function fmtMoney(n: number) {
  const sign = n < 0 ? '−' : '+'
  return `${sign}$${Math.abs(n).toFixed(0)}`
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
export function fmtRange([lo, hi]: [number, number]) {
  const sign = hi < 0 ? '−' : '+'
  return `${sign}$${Math.abs(lo).toFixed(0)} to $${Math.abs(hi).toFixed(0)}`
}
