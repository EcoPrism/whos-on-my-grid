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
- 2026-10-27, ground truth first (`GRID_BRIEF_SOURCE=full`). A reviewer checked the Bellevue brief
  line by line: "no nearby data center building is confirmed" was false (two Colocation Northwest
  sites within three miles, one half a mile away), the +$13 bill figure was a stale statewide
  number, and only the sentence the engine wrote itself held. A 30-address test set
  (`eval/addresses.json`, oracle in ranges, scored by `eval/run_eval.py`) put the agent-only build at
  4/30, with 23 of 26 facility rows reporting nothing and 67 of 180 section drafts truncated. The
  fix is the README's step 5: `app/ground/` gathers facilities from PeeringDB and OpenStreetMap
  (Overpass, clustered into campuses, nearest first), the serving utility from HIFLD's territory
  map (overlapping polygons disambiguated with EIA-861 customer counts, county lists and the
  address's city), residential prices from EIA-861M (state, monthly) and EIA-861 (this utility,
  annual, joined on the EIA utility number HIFLD carries), and large-load tariffs from a hand-curated
  `data/tariffs.json`. Spark now writes around a facts block: it cannot add or remove a facility,
  the price block is the engine's (`price.as_of` labels the period), the Protection tile comes from
  the tariff table, the noise line is modeled from distance, the strip is ordered bill, water,
  noise, and the band is capped when nothing is within five miles. New facility status `rejected`
  for a voted-down campus. Muse Spark counts its reasoning in completion tokens, so the draft budget
  is now 12,000 and the verifier's 4,096. Full test set on the grounded build: 26/30 (grid 28, bill 30, protection 30, strip 30,
  hard-fail signatures 28). The four left need a source this step does not have: the Prince William
  Digital Gateway hearing (Manassas), New Albany's construction that OpenStreetMap has not tagged,
  Project Blue's rejection in Tucson, and the operator of Apple's unmapped Maiden buildings. Three
  oracle rows were corrected after the map showed their campus outside the five-mile ring (Council
  Bluffs, Eagle Mountain, Huntsville). Runs live in `eval/runs/` (gitignored).
- 2026-10-28, the brief streams. A full-mode brief took 96 s to the first pixel: Spark's five
  drafts (16 to 29 s, in parallel), then the at-your-house draft (19 s), then 33 claims verified
  four at a time (about 45 s). Now `POST /api/brief/stream` emits the brief in stages as
  newline-delimited JSON: a partial brief once the ground truth is in (map, utility, bill range,
  engine-written strip lines, every section marked pending), a fresh partial as each section
  lands, a count per verified claim, then the finished brief. The page moves to the brief on the
  first event, shows a three-step progress line with elapsed time, breathes on the pending tiles,
  and ticks the claim count. Facts are on screen in about 9 s; sections land between 23 and 35 s.
  Total time also fell: in full mode the strip draft anchors to the facts block, so it runs in
  parallel with the sections, and the verifier runs eight claims at a time. Facility names are now
  unique (two clusters of the same operator get the compass direction from the address), which
  also fixes duplicate React keys on the map. The address box passes typed text through when
  Google's autocomplete widget is mounted but blocked, and a dropdown of test-set addresses sits
  under it in agent and full mode.
- 2026-10-28, step 4, perception and hearings. Two offline indexers and two file-backed
  providers. `app.perception.index` covers an area's five-mile ring with 1.2 km tiles at 1 m per
  pixel, fetches the earlier NAIP vintage from Planetary Computer's keyless crop endpoint (its
  `naip` collection ends at 2023; a tile that straddles two quarter quads is composited) and the
  latest from USDA FPAC's imagery service (2025 for OH, VA, AZ), runs SAM 3.1 (`sam-3.1`, Meta
  Model API, concept prompt "building", decoded with Meta's `meta-sam-parser`) on both, turns
  masks into Mercator polygons with the latitude correction, keeps roofs of two acres or more,
  and diffs the vintages: no earlier overlap is `new`, thirty percent larger is `expansion`. A
  roof is counted as data-center construction only when it adjoins a facility the database
  lists; other large roofs are shown but not counted, because the imagery cannot say what they
  are. `app.hearings.index` reads a meeting's agenda index points and closed captions from the
  Granicus JSON index, cuts the chosen windows of the recording into ten-minute mono WAV chunks
  (bundled ffmpeg), sends them to Muse Voice Transcribe in diarization mode, shifts the turns to
  recording time, scores agreement with the captions where both exist, and asks Muse Spark to
  label each speaker's role from the transcript; the words stay verbatim. Both write committed
  JSON under `data/perception/` and `data/hearings/`; the brief reads the index, so a request
  never waits on imagery or audio. Coming becomes `measured` (`sam-3.1`) with green footprints
  and an engine summary; Hearing becomes `measured` (`muse-voice-transcribe-1.0`, or `null` when
  the archive's own captions were used) with dated, timestamped quotes, and its claims cite the
  archive page while the verifier is handed the transcript. Votes on named campuses (Tucson's
  Project Blue rejection on 2025-08-06; Prince William's Digital Gateway rezoning, voided by the
  court and not appealed on 2026-04-14) are hand-entered decisions that appear in Coming as
  `rejected` with the official page as a claim. Archive research: Prince William, Loudoun and
  Pima are on Granicus (player page, `JSON.php` index points and captions, `DownloadFile.php`
  media redirect; the media host refuses a bare library User-Agent); the Digital Gateway
  marathon (12–13 Dec 2023, clip 3410, 26.8 hours) has no captions, so it needs the audio pass;
  Pima's June 2025 Project Blue video is missing from the archive; Tucson has no non-video-
  platform recording, so its written Legal Action Report is the source. Eval: measured roofs
  beside listed data centers count toward `announced_min`; hearing is scored where a hook is
  expected and the county is indexed.
- Streaming briefs now say what is final and what is a draft. While a brief streams, facts
  (map, facilities, utility, prices, bill number) look finished; every sentence a model wrote
  carries a Draft tag with no confidence, the headline shows a placeholder until a section
  exists, the at-your-house strip and claims appendix say the check is running, and Share is
  disabled until every claim is checked. A sticky progress strip explains the split and
  becomes a one-line "Checked. N claims, M supported, in S s" when the stream ends. Hearing
  quotes drop leading procedural sentences (captions run the chair's "moved and seconded"
  into the next speaker), so a quote starts at the speaker's own words.
- 2026-10-28, closing the test set and demo hygiene. The brief cache is stamped with an engine
  fingerprint (a hash of `services/api/app`, the schema and the curated data); a request for an
  address whose cached brief was made by another engine regenerates it, while the old link still
  opens. `data/facilities.json` is a second curated table: sites the maps draw without an operator,
  with the official page that names them. An operator-less cluster inside an entry's radius takes
  the operator and gets its own claim against that page (Apple's Maiden campus, from Apple's August
  2025 release); the map record's claim still says only what the map shows. The facility lookup
  now reaches ten miles: the ring stays five, and when it holds fewer than five facilities the
  brief names the nearest campus with a known operator beyond it (Meta at Eagle Mountain and
  Huntsville, Google at Council Bluffs), as a `beyond_ring` field, a sentence and a claim, never
  counted among the five-mile facilities. The engine now owns the facility-count card line; a
  drafted line that disagreed with the count is dropped. CLAUDE.md added.
- 2026-10-28, two things the eval rerun exposed. The Census geocoder's geographies endpoint (the
  one that adds the county) returned 502 for half an hour while its locations endpoint kept
  answering, and every brief failed with it; the geocoder now falls back to the locations
  endpoint and takes the county from the FCC area API (keyless), so a county outage degrades to
  "county unknown" instead of "no brief". And a campus is now measured by its nearest building,
  not its centroid: the ten-mile query pulled more of Meta's Gallatin buildings into one cluster
  and the centroid slid from 5.0 to 5.01 miles, dropping the campus from the ring. Any part of a
  campus inside five miles puts it on the list, and the noise line gets the nearest wall.
  Eval after all of this (`eval/runs/step6`): 28 of 30. Maiden, Tucson and Manassas now pass;
  New Albany waits on the SAM run; Elk Grove is a model-variance miss (the row wants PJM capacity
  costs named in the bill attribution and Spark left them out this run).
