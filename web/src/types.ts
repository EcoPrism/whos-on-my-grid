// Mirrors schema/brief.schema.json. Keep the two in step.

export type Status = 'measured' | 'reported' | 'modelled' | 'unavailable'
export type SectionId = 'on_your_grid' | 'coming' | 'your_bill' | 'protection' | 'hearing'
// A claim may also belong to the plain-language strip under the hero.
export type ClaimSection = SectionId | 'at_your_house'
export type HouseTopic = 'bill' | 'water' | 'noise' | 'land' | 'air' | 'grid' | 'taxes' | 'other'
export type Verdict = 'supported' | 'contradicted' | 'unverifiable' | 'unchecked'

export interface Source {
  title: string
  url: string
  retrieved_at: string
  page?: number | null
  quote?: string
}

export interface Facility {
  name: string
  codename?: string | null
  operator: string
  operator_confidence?: number
  distance_km: number
  status: 'live' | 'under_construction' | 'announced'
  estimated_mw?: number | null
  mw_basis?: 'filed' | 'reported' | 'class_estimate' | null
  // An inference from distance, never utility data. Rendered as 'likely'.
  shares_substation?: boolean | null
  lat?: number
  lon?: number
}

export interface Construction {
  label?: string
  distance_km: number
  footprint_acres_then: number
  footprint_acres_now: number
  vintages: [number, number]
  in_database?: boolean
  polygon?: [number, number][]
}

export interface Price {
  currency: string
  rate_now: number
  rate_then: number
  trend_pct: number
  window_months: number
  typical_household_kwh_month: number
  attribution?: string | null
}

export interface Tariff {
  large_load_tariff: 'in_force' | 'proposed' | 'none_found' | 'unknown'
  name?: string | null
  protects_households?: boolean | null
  docket?: string | null
}

export interface Said {
  speaker_role: string
  speaker_name?: string | null
  quote: string
  timestamp_s?: number | null
}

export interface Hearing {
  next_date: string | null
  body: string | null
  subject?: string | null
  last_meeting_date?: string | null
  last_meeting_said?: Said[]
}

export interface Section {
  status: Status
  confidence: number
  model: string | null
  summary: string
  gap?: string | null
  sources: Source[]
  facilities?: Facility[]
  construction?: Construction[]
  price?: Price
  tariff?: Tariff
  hearing?: Hearing
}

export interface HouseLine {
  text: string
  topic: HouseTopic
  status: Status
  confidence: number
  sources: Source[]
}

export interface Claim {
  id: string
  section: ClaimSection
  text: string
  source: Source
  drafted_by?: string
  verdict: Verdict
  verified_by?: string | null
  verifier_note?: string | null
}

export interface Brief {
  brief_id: string
  generated_at: string
  source_mode: 'fixtures' | 'agent' | 'full'
  fixture?: boolean
  address: {
    display: string
    lat: number
    lon: number
    state: string
    county?: string
    zip: string
    utility?: string | null
  }
  headline: {
    ai_rent_usd_per_month: number | null
    ai_rent_range_usd_per_month?: [number, number] | null
    percentile: number | null
    band: 'low' | 'medium' | 'high' | 'critical'
    one_liner?: string
  }
  sections: Record<SectionId, Section>
  claims: Claim[]
  at_your_house?: HouseLine[]
  card: { title: string; lines: string[]; footer?: string }
}
