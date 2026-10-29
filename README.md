# Who's On My Grid

Type any US address. Get an honest answer to three questions: **what is on my grid, what is
coming, and what has it done to my bill.**

Data centers are the fastest-growing new load on the US grid, and the people who live next to them
find out last. The facility is announced under a codename, permitted at a county meeting most
residents never hear about, and connected to the same local grid that serves their street. The
costs arrive later, as a higher bill, a louder night and a rate case in a docket nobody reads. The
data to answer the three questions is public, but it sits in six different places, in formats built
for engineers and lawyers, and none of them know your address.

Who's On My Grid turns one address into one brief and one card. The brief has five sections:

| Section | Question it answers |
|---|---|
| On your grid | Which data-center facilities are within five miles, who operates them, including the operator behind a codename, and that they are served by the same utility as you. Which substation serves an address is not public data, so the brief never claims it; at most it says a facility is likely on the same one, and says that is inferred |
| Coming | New large-roof construction visible from the air between the two most recent public aerial-imagery vintages, and announced or permitted campuses |
| Your bill | What your state's residential price has done over two years, what that means per month for a typical home, shown as a range because it is modeled, and what the people who set rates say about why |
| Protection | Whether your state has a large-load tariff, and the sentence the card exists for: does it shield households, yes, in part, no or not yet, with the page that says so |
| Hearing | When the next county or commission hearing is, and what was said at the last one, with who said it |

Under the hero sits one strip, **What this means at your house**: three or four plain-language
sentences a resident would screenshot for a neighbor. The bill, the water the campuses are permitted
to use compared with homes, how close the nearest building is and what neighbors have said about the
noise, the acres of field or forest now roof, and the other side in the same breath, the share of local
taxes the data centers pay. Each sentence still carries its status, confidence and sources. The cards
are for the reporter; the strip is for everyone.

Every section is one of four kinds, **measured**, **reported**, **modeled** (schema value `modelled`)
or **unavailable**, and
carries its sources, a confidence level and the model that produced it. The brief says plainly when
it does not know. It never claims that a data center caused a bill increase; it shows the numbers
and cites who attributes what.

Built for the Meta Global AI Developer Hackathon, 26 October to 4 November 2026. Startups track,
Push the Frontier.

## The models

Four Meta models sit on the critical path. Each does the one job it was built for, and each section
of the brief is footered with the model that produced it.

| Role | Model | Job |
|---|---|---|
| Reads and conducts | Muse Spark (`muse-spark-1.3`, Meta Model API) | Runs the investigation with search grounding; reads the large-load tariff and the open rate case whole (1M-token context, direct document input) and drafts every claim with a page-level citation |
| Sees | SAM 3.1 (`sam-3.1`, Meta Model API) | Segments public-domain USDA aerial imagery across the two most recent vintages; measures campus footprints and flags new large-roof construction that no database lists yet |
| Hears | Muse Voice Transcribe (`muse-voice-transcribe-1.0`) | Speaker-attributed transcripts of county and utility-commission hearings, so the brief knows a commissioner said it and not a resident |
| Verifies | Muse Spark Open (`meta-models/muse-spark-open` via Baseten, open weights) | An independent model re-checks every claim against its quoted source. Verdicts: supported, contradicted, unverifiable. Disagreements are shown, not hidden |

Two more are optional and marked as such in the brief:

- **Watches**: Muse Glimmer (open weights, Apache-2.0) as a sentinel on a single GPU, scanning new
  filings and imagery for watched ZIP codes. Addresses never leave the machine that runs it.
- **Built with**: Muse Code, for this week's code. The build log is in `docs/build-log.md`.

What distinguishes this from a search summarizer is that the models perceive and check the
physical and civic record: they see the construction, hear the hearing and read the filing.

## How it is built

The build runs inside out from a single contract, the Brief JSON (`schema/brief.schema.json`).
Nothing is wired to real data until the page already works on fixtures.

1. **Dummy repo.** The schema, fixture briefs with fictional operators, this README.
2. **UI on fixtures.** Address box, brief page, share card, versus card. `BRIEF_SOURCE=fixtures`.
3. **Agent-only backend.** Spark produces the whole brief from the address alone, cited from its
   own knowledge (no search API yet); the service fetches every cited page and Spark Open verifies
   each claim against it. Every section is `reported`. `BRIEF_SOURCE=agent`.
4. **Perception.** SAM 3.1 on two imagery vintages makes "Coming" `measured`. Voice Transcribe on
   pre-indexed hearings for a first set of counties makes "Hearing" `measured`. Both run as
   offline indexers (`app.perception.index`, `app.hearings.index`) whose output is committed
   under `data/regions/us/perception/` and `data/regions/us/hearings/`; the brief reads the
   index, so a request never waits on imagery or audio. Areas and bodies covered so far:
   `data/regions/us/perception/areas.json`, `docs/counties.md`. Votes on named campuses (a rejection, a court-voided rezoning) are
   hand-entered decisions in the hearing sources and appear in "Coming" with the page that says
   so.
5. **Ground-truth providers.** Facilities from PeeringDB and OpenStreetMap, serving utility from
   HIFLD's service-territory map, residential prices from EIA-861M (state, monthly) and EIA-861
   (this utility, annual), large-load tariffs from a hand-curated table
   (`data/regions/us/tariffs.json`), operators the maps leave blank from a second one
   (`data/regions/us/facilities.json`, each with the page that names them). The engine looks ten miles out and names the nearest campus past the ring.
   The engine owns existence, location, distance, utility and price; Spark writes the sentences
   around them and adds what no dataset holds (announced and rejected campuses, codenames,
   attributions, hearings). `BRIEF_SOURCE=full`. Scored against a 30-address test set in `eval/`.
   `POST /api/brief/stream` sends the brief as it is made (newline-delimited JSON): the facts and
   the map within seconds, each section as Spark finishes it, a count as claims are checked, then
   the finished brief. The page opens on the first event and fills in.
6. **Watch mode, hosted demo, video.**

```
address ──► brief service ──► Spark (reads, conducts; search grounding)
                                ├─ SAM 3.1 ............ footprints, new construction
                                ├─ Voice Transcribe ... hearing transcripts, vote dates
                                └─ data providers ..... facilities, substations, prices
                                        │
                              Spark Open (verifies every claim)
                                        │
                              brief + share card ──► watch mode ──► change alerts
```

## Run it

Two processes: the brief service (`services/api`, Python 3.13 with [uv](https://docs.astral.sh/uv/))
and the UI (`web`, Vite). The UI proxies `/api` to the service.

```
cd services/api
cp .env.example .env            # fixtures mode works with no keys
uv sync
uv run pytest                   # offline suite, fake providers
uv run uvicorn app.main:create_app --factory --reload --port 8000

cd ../../web
npm install
npm run dev                     # http://localhost:5173
```

For agent or full mode set `GRID_BRIEF_SOURCE=agent` (Spark from its own knowledge) or
`GRID_BRIEF_SOURCE=full` (ground truth first) and `GRID_LLM_PROVIDER=openai` in `services/api/.env`
and fill in `GRID_OPENAI_API_KEY` (this project's virtual key on the LLM gateway; the model alias
`meta-flagship` is Muse Spark 1.3) and `GRID_BASETEN_API_KEY` (Muse Spark Open, the verifier). The
service refuses to start in agent mode without them. `uv run pytest -m live --run-live` sends one
small call to each endpoint to prove the keys and the structured-output path. Optional:
`VITE_GOOGLE_MAPS_API_KEY` in `web/.env` turns the address box into Google Places autocomplete.

The two step-4 indexers need `GRID_META_API_KEY` (Meta Model API, direct, from dev.meta.ai);
the brief service itself never does. `uv sync --group index` adds their dependencies
(numpy, Pillow, shapely, rasterio, meta-sam-parser, a bundled ffmpeg). Then:

```
cd services/api
uv run python -m app.perception.index --area new_albany          # SAM 3.1 on NAIP 2023 vs 2025
uv run python -m app.hearings.index --meeting loudoun-2025-03-18 --captions-only
uv run python -m app.hearings.index --meeting pwc-2023-12-12 --audio data/regions/us/hearings/audio/pwcgov_3410.mp3
```

Imagery is keyless and public domain (Planetary Computer for the earlier vintage, USDA FPAC for
the latest). Recordings come from the official archive page (download the MP3 in a browser into
`data/regions/us/hearings/audio/`, or pass `--download`); `--captions-only` builds the transcript from the
archive's closed captions where it publishes them, and the section then says no model of ours
produced the words.

Full mode needs no further keys. PeeringDB's US facility list, the EIA workbooks and the
OpenStreetMap query are free and keyless; snapshots are cached under `data/ground/` (gitignored).
Overpass is queried on `overpass.openstreetmap.fr` first (the only mirror reachable from some
networks), then the others in `GRID_OVERPASS_ENDPOINTS`.

### The test set

`eval/us/addresses.json` holds thirty street-level pins with an oracle for each: facility bucket,
operators that must be named, serving utility, bill direction and size, tariff status, which
consequence lines must appear and which phrases are hard fails. `eval/run_eval.py` reverse-geocodes
each pin to a numbered address (cached in `eval/us/resolved.json`), posts it to a running API, and scores
the briefs per dimension into the `--out` directory, or `eval/runs/<region>/<name>/` with `--name`:

```
cd services/api && GRID_BRIEF_SOURCE=full GRID_DATA_DIR=eval/runs/full/cache   uv run uvicorn app.main:create_app --factory --port 8010
python eval/run_eval.py --api http://localhost:8010 --out eval/runs/full
```

Ireland's ten rows are in `eval/ie/addresses.json` (named public places only: a shopping centre,
a railway station, civic offices, quays). `python eval/run_eval.py --region ie --name <run>`
sends each row as typed with `region: "ie"` (no reverse geocoding), scores distances in km and
the bill in euro, and fails any brief that leaks US units. Run the API with `GRID_REGIONS=us,ie`.

Hearing is scored where a hook is expected and the county is indexed (`docs/counties.md`), and
as information only elsewhere. Measured construction that adjoins a listed data center counts
toward a row's "announced or under construction" expectation.

Generated briefs are cached in `data/briefs/` by a hash of the address, gitignored.

Optional: `VITE_GOOGLE_MAPS_API_KEY` in `web/.env` turns the address box into Google Places
autocomplete (US only). `GRID_BASETEN_API_KEY` is optional; without it claims stay `unchecked`.
`GRID_ALLOWED_COUNTRIES=US` gates `/api/brief` behind an edge that sets `GRID_COUNTRY_HEADER`
from the visitor IP; leave it empty locally.

### Ireland

`GRID_REGIONS=us,ie` adds Ireland to the same process (off by default). The home page then shows a
"US · Ireland" switch; an Irish brief is in kilometres and euro, spells "data centre", and its
sources are: PeeringDB (IE and GB) and OpenStreetMap for facilities, ESB Networks as the
distribution system operator (one polygon built from Tailte Éireann's provinces, CC BY 4.0, see
`data/regions/ie/README.md`), Eurostat `nrg_pc_204` for the residential price (same half-year,
two years apart) with the CRU's 4,200 kWh typical consumption, the CRU's December 2025
data-centre connection policy, and An Coimisiún Pleanála decisions matched by distance. Addresses
are geocoded with OpenStreetMap Nominatim (`GRID_NOMINATIM_URL`; the public instance is for dev
and eval only, one request a second) and rounded to 3 decimals before anything else sees them.
`GRID_IE_GEOCODER=fake` answers only the Irish test set, for fixtures mode. Irish briefs are
deleted after `GRID_BRIEF_TTL_DAYS` days (0 keeps them). The what-if is US only.

## Deploy

One container serves the API and the built web app (`Dockerfile`, build context the repo root).
On Azure it runs as a single Container App in its own resource group with a file share for the
brief cache and datasets, two tables for sign-ins and usage, and a Key Vault for the keys
(`infra/main.bicep`, `scripts/deploy.ps1`, runbook in `docs/deploy.md`).

Making a brief for a new address needs a Google sign-in and counts against a daily quota per
person and overall, because each one spends model tokens. Opening a brief, and running one of the
test-set addresses, needs no sign-in. The usage tables hold an email and brief ids, never an
address. The home page also shows what PeeringDB lists today and two "in house terms" lines; the
constants behind those are in `data/equivalences.json`, each with the page and sentence it comes from.

## What was built when

Everything in this repository was written during the hackathon, from 27 October 2026. The first
commit is dated.

The grid-stress scoring engine that EcoPrism wrote in September 2026 is published separately as
[gridscout-core](https://github.com/EcoPrism/gridscout-core) (Apache-2.0, published 26 October
2026). This project does not depend on it yet. If it is adopted as a data provider in step 5 it
will be pinned at a tag and listed here as pre-existing. No EcoPrism customer or proprietary data
is used anywhere in this project.

## Coverage and honesty

- US addresses, and Irish addresses when Ireland is enabled (no aerial imagery and no hearing
  transcripts there yet). In the US, aerial imagery and state prices cover the whole country. Facility data is dense
  in data-center metros and sparse elsewhere. Hearings are covered for the counties that have been
  indexed, listed in `docs/counties.md`. The brief says which applies, per section.
- A claim is text plus a verbatim quote plus a source URL. The verifier checks that the quote exists
  in the source and supports the claim.
- Addresses are personal data. Briefs are keyed by a hash of the normalized address; addresses are
  not logged. Watch mode stores a ZIP code only.
- Data sources and their terms: USDA NAIP imagery (public domain), US EIA (public domain), HIFLD
  service territories (public), OpenStreetMap (ODbL, attribution required), PeeringDB (research use
  permitted, bulk redistribution and commercial use prohibited; queried per location only),
  Eurostat (reuse with acknowledgement), Tailte Éireann boundaries (CC BY 4.0), Nominatim
  (OSMF usage policy: geocoding shown with "© OpenStreetMap contributors"), county
  and commission archives (public record, fetched from the official archive, never from video
  platforms).

## License

Apache License 2.0. See [LICENSE](LICENSE).
