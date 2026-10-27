# Build log

Dated entries of what was built, with which tools. Judges can use this to tell event work apart
from anything pre-existing.

## 2026-10-27
- Repository created. README (vision), `schema/brief.schema.json` (the contract), five fixture
  briefs with fictional operators, coverage and build-log docs. No code wired to real data.
- Web app (`web/`, Vite + React + TypeScript + Tailwind + Leaflet) running on the fixtures:
  address box, brief page (five sections with status rail, five-mile map, claims appendix with
  verifier verdicts), share card. `BRIEF_SOURCE=fixtures` is the only mode so far.
- Step 3, agent-only backend (`services/api`, Python 3.13, FastAPI, uv). `POST /api/brief` takes an
  address and returns a schema-valid brief: US Census geocoder for coordinates, county and ZIP;
  Muse Spark 1.3 (gateway alias `meta-flagship`, through the Betahub LLM Gateway with the OpenAI
  SDK, pattern copied from lookupsoccer) drafts the five sections in parallel with strict
  JSON-schema output derived from `schema/brief.schema.json`; the service fetches every cited
  URL and Muse Spark Open on Baseten gives each claim a verdict against the page text. No search
  API: Spark drafts from its own knowledge, so every section is `reported` and unverifiable
  citations are shown as such. Briefs cached under `data/briefs/{hash}.json`; addresses are never
  logged. UI is now an API client (`web/src/lib/api.ts`), with optional Google Places
  autocomplete. 33 offline tests with fake providers; two live canaries behind `--run-live`.
  Muse Code wrote the service and the UI changes.
- Brief page redesigned as one screen: the map is the hero with the headline card on it, each
  facility is tied to the address by an animated line (color by status, weight by MW, dashes flow
  toward the address, pulse ring at the address), five section tiles open one detail at a time,
  claims appendix and share card fold away. The citation fetcher refuses non-public hosts on
  every redirect hop, and connects to the vetted IP with Host and SNI pinned to the name, so
  DNS rebinding cannot slip past the check (SSRF findings from the automated security review).
- Design review fixes. The hero no longer says facilities "share your substation": address-level
  substation mapping is not public, so the headline says "on your local grid, served by Dominion
  Energy", the substation flag is described in the schema as an inference and rendered as "likely",
  and it no longer thickens map lines. The Ashburn fixture now carries all fifteen facilities with
  coordinates (distances computed from them), the map frames them clear of the headline card and
  shows a "15 facilities plotted · 9 within a mile" badge, so the evidence for the headline count
  is on screen. The bill number is shown as a range (`headline.ai_rent_range_usd_per_month`, ±20%
  household usage) in the modeled color with the same "Modeled · 78%" tag as its card; fixture bill
  figures are now derived from the price block so hero, card and section agree. The Protection
  tile answers its own question ("Yes, in part. … in force and keeps some build-out costs off
  household bills"), derived from the tariff object, and the prompt asks Spark to lead the summary
  with that answer. New layer, not a sixth section: `at_your_house`, three or four plain-language
  sentences under the hero (bill, water, noise, land, air, grid, taxes), each with status,
  confidence and sources. In agent mode the bill sentence is computed from the price block and a
  sixth Spark call drafts the rest from the five summaries, with claims the verifier checks like
  any other. US spelling throughout the UI, fixtures, prompts and README.
- 2026-10-27, keys and gates: gateway team `grid` / key `grid-dev` minted by API, Baseten key
  `whos-on-my-grid-dev`, verifier id corrected to `meta-models/muse-spark-open` (confirmed from
  Baseten's model list). The verifier is optional: no Baseten key, claims stay `unchecked` and the
  card footer says so. Google Places autocomplete live with a referrer-restricted browser key
  (project ecoprism-ecoutil, Places API New + Maps JS); the loader now uses the API's `callback`
  parameter since `importLibrary` is not ready at script onload. Optional US-only gate on
  /api/brief (GRID_ALLOWED_COUNTRIES, trusts an edge-set country header; off locally).
