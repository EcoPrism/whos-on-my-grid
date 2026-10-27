import type { Brief } from '../types'

// BRIEF_SOURCE=fixtures: the five briefs at the repo root are the whole universe.
// Later modes fetch /api/brief?address=... and return the same shape.
const modules = import.meta.glob('../../../fixtures/briefs/*.json', { eager: true, import: 'default' }) as Record<string, Brief>

export const fixtures: Record<string, Brief> = Object.fromEntries(
  Object.entries(modules).map(([path, brief]) => [path.split('/').pop()!.replace('.json', ''), brief]),
)

export const fixtureKeys = Object.keys(fixtures)

export function getBrief(key: string): Brief | undefined {
  return fixtures[key]
}

// Match a typed address to a fixture. Good enough for the dummy stage: any
// token of the fixture's display line or key appearing in the input.
export function resolveAddress(input: string): string | undefined {
  const q = input.toLowerCase()
  if (!q.trim()) return undefined
  for (const [key, b] of Object.entries(fixtures)) {
    const tokens = [key, ...b.address.display.toLowerCase().split(/[\s,]+/), b.address.zip]
    if (tokens.some((t) => t.length > 2 && q.includes(t))) return key
  }
  return undefined
}
