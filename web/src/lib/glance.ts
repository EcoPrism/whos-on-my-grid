import type { GlanceItem, HouseLine, HouseTopic } from '../types'

// The working behind a tile, for the tap-to-see popover. A what-if counter
// takes the impact block's own basis, or the matching strip line's text and
// sources; a brief tile takes the glance entry's sentence and sources.

export interface Basis {
  text: string
  sources: HouseLine['sources']
}

export function basisFor(block: { basis?: string } | null | undefined, topic: HouseTopic, lines: HouseLine[] | undefined): Basis {
  const line = lines?.find((l) => l.topic === topic)
  const text = block?.basis ?? (line && 'basis' in line ? String((line as { basis?: unknown }).basis ?? '') : '')
  return { text: text || line?.text || '', sources: line?.sources ?? [] }
}

export function basisOf(item: GlanceItem): Basis {
  return { text: item.text ?? '', sources: item.sources }
}

// A tile value the counter can tick up to: the leading number of "0.5 miles",
// "12 acres" or "10", with the unit that follows it. Null for a word or a range.
export function numberOf(value: string | null): { n: number; unit: string } | null {
  if (!value) return null
  const m = value.match(/^(\d+(?:\.\d+)?)(.*)$/)
  if (!m) return null
  return { n: Number(m[1]), unit: m[2] }
}
