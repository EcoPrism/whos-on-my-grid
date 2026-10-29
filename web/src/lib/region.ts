import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { getHealth, isUnknownRegion, type Health, type RegionInfo } from './api'
import type { Brief } from '../types'

// Which region new briefs are made for. The viewer's pick is remembered in
// localStorage (a per-viewer convenience: it may be missing or blocked, so
// every access is guarded) and is only ever a hint: the API's own region list
// decides whether it is used.

const KEY = 'grid.region'

export function storedRegion(): string | null {
  try {
    return window.localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function setRegion(id: string): void {
  try {
    window.localStorage.setItem(KEY, id)
  } catch {
    /* storage blocked: the pick lasts for this page only */
  }
}

export function clearStoredRegion(): void {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    /* nothing to clear */
  }
}

// The US strings, for an API that predates per-region fields.
const US_DEFAULTS: Required<Omit<RegionInfo, 'id' | 'label' | 'locale'>> = {
  countries: ['US'],
  places_country: ['us'],
  scenarios: true,
  placeholder: '21715 Filigree Ct, Ashburn, VA',
  address_label: 'Street address, city, state',
  geocoder_attribution: null,
  sources_line: 'PeeringDB, OpenStreetMap, EIA',
  brief_ttl_days: 0,
}

export function regionDefaults() {
  return US_DEFAULTS
}

// The health body's row for `id` (the requested region by default).
export function regionInfo(health: Health | null | undefined, id = health?.region): RegionInfo | null {
  if (!health || !id) return null
  return health.regions?.find((r) => r.id === id) ?? null
}

// The region a brief was made for, found by its locale's country in the
// deployment's region list (`ie` for country IE). Older briefs are US.
export function regionOfBrief(regions: RegionInfo[] | undefined, brief: Pick<Brief, 'locale'>): RegionInfo | null {
  const id = (brief.locale?.country ?? 'US').toLowerCase()
  return regions?.find((r) => r.id === id) ?? null
}

// --- the region list, shared by the pages and the footer -------------------

// One health request without a region, shared by every first reader (the home
// page's start-up, the footer, About, a brief's attribution line). Refreshes
// after sign-in or a region switch call getHealth directly.
let baseOnce: Promise<Health> | null = null
export function baseHealth(): Promise<Health> {
  baseOnce ??= getHealth().catch((e: unknown) => {
    baseOnce = null
    throw e
  })
  return baseOnce
}

// A fresh one (the home page wants the current sign-in and quota each time it
// opens); later first readers share it.
function refreshBaseHealth(): Promise<Health> {
  baseOnce = null
  return baseHealth()
}

// The region the page is about right now: the home page's pick, or the region
// of the brief on screen. The footer's data line reads it.
interface Current {
  regions: RegionInfo[]
  id: string | null
}
let current: Current = { regions: [], id: null }
const listeners = new Set<() => void>()

export function publishRegion(regions: RegionInfo[] | undefined, id: string | null | undefined): void {
  const next = regions ?? current.regions
  const nextId = id ?? null
  if (next === current.regions && nextId === current.id) return
  current = { regions: next, id: nextId }
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

// The regions this deployment serves and the one on screen. The first reader
// loads the list; until it arrives (or if it fails) the list is empty.
export function useCurrentRegion(): { regions: RegionInfo[]; info: RegionInfo | null } {
  const snap = useSyncExternalStore(subscribe, () => current, () => current)
  useEffect(() => {
    if (snap.regions.length > 0) return
    baseHealth()
      .then((h) => publishRegion(h.regions, current.id ?? h.region))
      .catch(() => undefined)
  }, [snap.regions.length])
  return { regions: snap.regions, info: snap.regions.find((r) => r.id === snap.id) ?? null }
}

// --- the home page's region -----------------------------------------------

const OFFLINE: Health = {
  ok: false,
  mode: 'offline',
  examples: [],
  test_addresses: [],
  auth: 'off',
  google_client_id: null,
  user: null,
  quota_per_user_day: 0,
}

// Health for the viewer's region. Start-up asks without a region first; a
// stored id is used only when that list has it, and then health is fetched
// again for it. A 422 unknown_region on any regional call clears the stored
// id and falls back to the API's own pick.
export function useRegion() {
  const [health, setHealth] = useState<Health | null>(null)

  const adopt = useCallback((h: Health) => {
    setHealth(h)
    publishRegion(h.regions, h.region)
  }, [])

  // The API's pick, without a region; the fallback for every failure below.
  const fallback = useCallback(() => {
    getHealth()
      .then(adopt)
      .catch(() => setHealth(OFFLINE))
  }, [adopt])

  useEffect(() => {
    let cancelled = false
    refreshBaseHealth()
      .then(async (base) => {
        const wanted = storedRegion()
        const known = (base.regions ?? []).some((r) => r.id === wanted)
        if (!wanted || !known || wanted === base.region) {
          if (wanted && !known) clearStoredRegion()
          if (!cancelled) adopt(base)
          return
        }
        try {
          const h = await getHealth(wanted)
          if (!cancelled) adopt(h)
        } catch (e) {
          if (isUnknownRegion(e)) clearStoredRegion()
          if (!cancelled) adopt(base)
        }
      })
      .catch(() => {
        if (!cancelled) setHealth(OFFLINE)
      })
    return () => {
      cancelled = true
    }
  }, [adopt])

  // The viewer picks a region: remember it and load its health.
  const choose = useCallback(
    (id: string) => {
      setRegion(id)
      getHealth(id)
        .then(adopt)
        .catch((e: unknown) => {
          if (isUnknownRegion(e)) {
            clearStoredRegion()
            fallback()
          }
        })
    },
    [adopt, fallback],
  )

  // Health again for the region on screen (after sign-in, a spent quota, or a
  // region the API no longer serves).
  const reload = useCallback(
    (unknown = false) => {
      if (unknown) {
        clearStoredRegion()
        fallback()
        return
      }
      const id = health?.region
      getHealth(id)
        .then(adopt)
        .catch((e: unknown) => {
          if (isUnknownRegion(e)) {
            clearStoredRegion()
            fallback()
          }
        })
    },
    [adopt, fallback, health?.region],
  )

  return { health, setHealth, choose, reload, info: regionInfo(health) }
}
