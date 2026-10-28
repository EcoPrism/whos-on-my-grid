import { useSyncExternalStore } from 'react'
import type { Brief } from '../types'

// Briefs in progress, keyed by brief id. Home starts a stream and moves to the
// brief page as soon as the first partial arrives; the page reads the latest
// state from here and re-renders on every event. Module state, not context, so
// the stream outlives the page that started it.

export type Stage = 'ground' | 'drafting' | 'verifying' | 'done' | 'error'

export interface Live {
  brief: Brief
  stage: Stage
  verified: number
  claims: number
  startedAt: number
  error?: string
}

const state = new Map<string, Live>()
const listeners = new Map<string, Set<() => void>>()

export function getLive(id: string): Live | undefined {
  return state.get(id)
}

export function setLive(id: string, next: Live) {
  state.set(id, next)
  listeners.get(id)?.forEach((fn) => fn())
}

export function updateLive(id: string, change: Partial<Live>) {
  const cur = state.get(id)
  if (cur) setLive(id, { ...cur, ...change })
}

function subscribe(id: string, fn: () => void) {
  let set = listeners.get(id)
  if (!set) {
    set = new Set()
    listeners.set(id, set)
  }
  set.add(fn)
  return () => {
    set!.delete(fn)
  }
}

export function useLive(id: string): Live | undefined {
  return useSyncExternalStore(
    (fn) => subscribe(id, fn),
    () => state.get(id),
    () => state.get(id),
  )
}
