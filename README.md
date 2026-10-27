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
   pre-indexed hearings for a first set of counties makes "Hearing" `measured`.
5. **Ground-truth providers.** Facilities, substations, service territory and prices from PeeringDB,
   OpenStreetMap, HIFLD and EIA. `BRIEF_SOURCE=full`.
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

For agent mode set `GRID_BRIEF_SOURCE=agent` and `GRID_LLM_PROVIDER=openai` in `services/api/.env`
and fill in `GRID_OPENAI_API_KEY` (this project's virtual key on the LLM gateway; the model alias
`meta-flagship` is Muse Spark 1.3) and `GRID_BASETEN_API_KEY` (Muse Spark Open, the verifier). The
service refuses to start in agent mode without them. `uv run pytest -m live --run-live` sends one
small call to each endpoint to prove the keys and the structured-output path. Optional:
`VITE_GOOGLE_MAPS_API_KEY` in `web/.env` turns the address box into Google Places autocomplete.

Generated briefs are cached in `data/briefs/` by a hash of the address, gitignored.

Optional: `VITE_GOOGLE_MAPS_API_KEY` in `web/.env` turns the address box into Google Places
autocomplete (US only). `GRID_BASETEN_API_KEY` is optional; without it claims stay `unchecked`.
`GRID_ALLOWED_COUNTRIES=US` gates `/api/brief` behind an edge that sets `GRID_COUNTRY_HEADER`
from the visitor IP; leave it empty locally.

## What was built when

Everything in this repository was written during the hackathon, from 27 October 2026. The first
commit is dated.

The grid-stress scoring engine that EcoPrism wrote in September 2026 is published separately as
[gridscout-core](https://github.com/EcoPrism/gridscout-core) (Apache-2.0, published 26 October
2026). This project does not depend on it yet. If it is adopted as a data provider in step 5 it
will be pinned at a tag and listed here as pre-existing. No EcoPrism customer or proprietary data
is used anywhere in this project.

## Coverage and honesty

- US addresses only. Aerial imagery and state prices cover the whole country. Facility data is dense
  in data-center metros and sparse elsewhere. Hearings are covered for the counties that have been
  indexed, listed in `docs/counties.md`. The brief says which applies, per section.
- A claim is text plus a verbatim quote plus a source URL. The verifier checks that the quote exists
  in the source and supports the claim.
- Addresses are personal data. Briefs are keyed by a hash of the normalized address; addresses are
  not logged. Watch mode stores a ZIP code only.
- Data sources and their terms: USDA NAIP imagery (public domain), US EIA (public domain), HIFLD
  service territories (public), OpenStreetMap (ODbL, attribution required), PeeringDB (research use
  permitted, bulk redistribution and commercial use prohibited; queried per location only), county
  and commission archives (public record, fetched from the official archive, never from video
  platforms).

## License

Apache License 2.0. See [LICENSE](LICENSE).
