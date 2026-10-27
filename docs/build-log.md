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
  facility is tied to the address by an animated line (colour by status, weight by MW, dashes flow
  toward the address, pulse ring at the address), five section tiles open one detail at a time,
  claims appendix and share card fold away. The citation fetcher refuses non-public hosts on
  every redirect hop, and connects to the vetted IP with Host and SNI pinned to the name, so
  DNS rebinding cannot slip past the check (SSRF findings from the automated security review).
