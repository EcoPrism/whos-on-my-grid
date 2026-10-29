import { US_LOCALE, type ClaimSection, type HouseTopic, type Locale, type Status } from '../types'
import { dcNoun } from './format'

// The words a reader sees for the engine's vocabulary. The schema values
// (measured, reported, modelled, unavailable; on_your_grid, coming, ...) are the
// contract with the API and never change; this file is the only place they
// are turned into English. Same words in every region.

export const STATUS_WORD: Record<Status, string> = {
  measured: 'From the data',
  reported: 'Written by AI, checked',
  modelled: 'Our estimate',
  unavailable: 'Not public',
}

// One clause each, for the footer legend, the about page and a tile's working.
export const STATUS_GLOSS: Record<Status, string> = {
  measured: 'read from a public dataset by the engine itself',
  reported: 'a model wrote it and cited a page; a second model checked the sentence against that page',
  modelled: 'our arithmetic over a cited figure, shown as a range, not a measurement',
  unavailable: 'nobody publishes it, and the brief says so',
}

// Confidence in three words instead of a percentage. The number itself stays
// in the claims list for anyone who wants it.
export function confidenceWord(c: number): 'solid' | 'likely' | 'rough' {
  if (c >= 0.75) return 'solid'
  if (c >= 0.5) return 'likely'
  return 'rough'
}

// What a section is called on the page. The data-center noun follows the
// brief's region ("centre" in Ireland).
export function sectionTitle(id: ClaimSection, locale: Locale = US_LOCALE): string {
  switch (id) {
    case 'on_your_grid':
      return `${capital(dcNoun(locale))}s near you`
    case 'coming':
      return 'Being built or proposed'
    case 'your_bill':
      return 'Your electric bill'
    case 'protection':
      return 'Who pays for the new power'
    case 'hearing':
      return 'Next public meeting'
    case 'at_your_house':
      return 'At your house'
    case 'scenario':
      return 'What-if'
  }
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// The concerns on the tiles, in the words people use for them.
export const TOPIC_WORD: Record<HouseTopic, string> = {
  bill: 'Electric bill',
  grid: 'Electricity',
  water: 'Water',
  noise: 'Noise',
  land: 'Land',
  air: 'Air',
  taxes: 'Taxes',
  other: 'Other',
}
