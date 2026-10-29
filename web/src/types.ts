// Mirrors schema/brief.schema.json. Keep the two in step.

export type Status = 'measured' | 'reported' | 'modelled' | 'unavailable'
export type SectionId = 'on_your_grid' | 'coming' | 'your_bill' | 'protection' | 'hearing'
// A claim may also belong to the plain-language strip under the hero.
export type ClaimSection = SectionId | 'at_your_house' | 'scenario'
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
  status: 'live' | 'under_construction' | 'announced' | 'rejected'
  estimated_mw?: number | null
  mw_basis?: 'filed' | 'reported' | 'class_estimate' | null
  // An inference from distance, never utility data. Rendered as 'likely'.
  shares_substation?: boolean | null
  lat?: number
  lon?: number
}

export interface Construction {
  label?: string
  // new: no roof there in the earlier imagery; expansion: a listed facility grew.
  kind?: 'new' | 'expansion'
  distance_km: number
  footprint_acres_then: number
  footprint_acres_now: number
  vintages: [number, number]
  in_database?: boolean
  // Within 1.5 km of a listed data center; only then is an unlisted roof counted.
  near_cluster?: boolean
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
  as_of?: string
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
  // On your grid: the nearest known campus past the five-mile ring, within ten.
  beyond_ring?: Facility
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

// Present only on a brief still being made (streamed from /api/brief/stream):
// which sections Spark has not drafted yet.
export interface PartialInfo {
  stage: 'ground' | 'drafting' | 'verifying'
  pending: SectionId[]
  drafted: number
  sections: number
}

export interface Brief {
  brief_id: string
  generated_at: string
  source_mode: 'fixtures' | 'agent' | 'full'
  fixture?: boolean
  engine?: string
  partial?: PartialInfo
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
  // disclosure: the AI-assisted line the share card prints in its footer band; the PNG prints the same.
  card: { title: string; lines: string[]; footer?: string; disclosure?: string }
}

// What the share card says, as the API rasterises it (GET /api/card/{id}.json).
export interface CardSpec {
  title: string
  lines: string[]
  big: string | null
  big_caption: string | null
  footer: string | null
  disclosure: string
  hypothetical: boolean
}

// The share menu reads this so the prefilled text, the link and the image agree.
export interface CardInfo {
  kind: 'brief' | 'scenario'
  id: string
  spec: CardSpec
  share_text: string
  url: string
  image_url: string
}

// --- what-if scenarios (schema/scenario.schema.json) -------------------------

export type Cooling = 'evaporative' | 'closed_loop'

// What the resident asks. The pin is rounded to 3 decimals by the API.
export interface ScenarioInputs {
  zip: string
  mw: number
  cooling: Cooling
  pin: { lat: number; lon: number } | null
}

// A strip line in a scenario: always modelled, with its working.
export interface ScenarioLine extends HouseLine {
  status: 'modelled'
  basis: string
}

// The engine's arithmetic. A block is null when a constant it needs has no
// cited page; `basis` is the working for the tap-to-see popover.
export interface Impact {
  power: {
    gwh_per_year: number
    homes_equivalent: number | null
    share_of_utility_homes: number | null
    basis?: string
  } | null
  water: { gal_per_day: number; homes_equivalent: number | null; basis?: string } | null
  land: { acres: number; football_fields: number | null; basis?: string } | null
  bill: {
    kind: 'shielded' | 'partial' | 'exposed' | 'unknown'
    range_usd_per_month: [number, number] | null
    basis?: string
  }
  taxes: { range_usd_per_year: [number, number]; basis?: string } | null
  jobs: { permanent: number; basis?: string } | null
  noise: { distance_km: number; db_at_pin: number | null; basis?: string }
  timeline: { construction_months: [number, number]; basis?: string } | null
}

export interface Scenario {
  scenario_id: string
  generated_at: string
  engine: string
  kind: 'scenario'
  disclosure: 'Hypothetical. Modelled, not measured.'
  inputs: ScenarioInputs
  place: {
    display: string
    state: string
    county?: string | null
    zip: string
    lat: number
    lon: number
    households: { count: number; source: Source } | null
  }
  baseline: {
    facilities: Facility[]
    facility_count: number | null
    utility: {
      name: string
      kind: string
      customers: number | null
      source: Source
      customers_source?: Source | null
    } | null
    price: Price | null
    tariff: Tariff | null
  }
  impact: Impact
  lines: ScenarioLine[]
  // The optional Spark paragraph (build step 4); null until it is asked for.
  interpretation?: {
    status: 'reported'
    text: string
    model: string
    confidence: number
    draft: boolean
  } | null
  claims: Claim[]
  card: { title: string; lines: string[]; footer: string; disclosure: string }
}
