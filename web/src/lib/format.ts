export function fmtMoney(n: number) {
  const sign = n < 0 ? '−' : '+'
  return `${sign}$${Math.abs(n).toFixed(0)}`
}

// The modeled bill change is shown as a range, never as a point estimate alone.
export function fmtRange([lo, hi]: [number, number]) {
  const sign = hi < 0 ? '−' : '+'
  return `${sign}$${Math.abs(lo).toFixed(0)} to $${Math.abs(hi).toFixed(0)}`
}
