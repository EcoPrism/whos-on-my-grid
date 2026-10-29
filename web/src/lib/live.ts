import { useSyncExternalStore } from 'react'
import type { Brief, Scenario } from '../types'

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
  endedAt?: number
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

// Scenarios, keyed by scenario id. Home and the what-if page hand a freshly
// made scenario over here before navigating, so the page opens from it
// without a second fetch. A scenario is finished when it arrives; there is
// no stage to track.

const scenarios = new Map<string, Scenario>()
const scenarioListeners = new Map<string, Set<() => void>>()

export function getLiveScenario(id: string): Scenario | undefined {
  return scenarios.get(id)
}

export function setLiveScenario(id: string, next: Scenario) {
  scenarios.set(id, next)
  scenarioListeners.get(id)?.forEach((fn) => fn())
}

function subscribeScenario(id: string, fn: () => void) {
  let set = scenarioListeners.get(id)
  if (!set) {
    set = new Set()
    scenarioListeners.set(id, set)
  }
  set.add(fn)
  return () => {
    set!.delete(fn)
  }
}

export function useLiveScenario(id: string): Scenario | undefined {
  return useSyncExternalStore(
    (fn) => subscribeScenario(id, fn),
    () => scenarios.get(id),
    () => scenarios.get(id),
  )
}
