import { useEffect, useRef, useState, useSyncExternalStore } from 'react'

// Motion on the what-if page is driven only by the engine's numbers, never by
// a model, and a reader who asked for less motion gets the final values at once.

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(onChange: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const mq = window.matchMedia(QUERY)
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}

function snapshot(): boolean {
  return typeof window !== 'undefined' && Boolean(window.matchMedia) && window.matchMedia(QUERY).matches
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)

// Eases from the value currently shown to `target` over `ms`. A new target
// mid-flight starts from wherever the number is, so it never jumps back.
// Under reduced motion (or ms <= 0) it returns `target` immediately.
export function useAnimatedNumber(target: number, ms: number): number {
  const reduced = usePrefersReducedMotion()
  const safe = Number.isFinite(target) ? target : 0
  const [value, setValue] = useState(safe)
  // What is on screen right now, read when a new target arrives.
  const shown = useRef(safe)

  useEffect(() => {
    if (reduced || ms <= 0) {
      shown.current = safe
      return
    }
    const from = shown.current
    if (from === safe) return
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      const v = from + (safe - from) * easeOutCubic(t)
      shown.current = v
      setValue(v)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [safe, ms, reduced])

  // Reduced motion snaps the held value too, so turning motion back on later
  // eases from where the number really is.
  if ((reduced || ms <= 0) && value !== safe) setValue(safe)
  return reduced || ms <= 0 ? safe : value
}
