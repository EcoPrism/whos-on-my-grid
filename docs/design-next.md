# Design: what-if scenarios, sharing, Europe and India

Four things the hackathon build does not do yet, designed against the code as it stands on
2026-10-29. Part 1 is the shape of each; part 2 is the low-level design: modules, signatures,
schemas, endpoints, data files, UI components and tests. Nothing here is built.

The rules in `CLAUDE.md` hold throughout. Every engine claim cites a page with a verbatim quote.
Facts from data are `measured`; arithmetic over cited constants is `modelled`; a model's sentences
are `reported`. Addresses are never logged. The gate guards only work that costs model tokens.

---

## Part 1. High-level design

### 1. "Drop a data center on my town" (what-if)

A what-if is the brief in the future tense. The engine already owns location, serving utility,
price series, tariff and nearby facilities. A scenario adds one hypothetical campus to that ground
truth and computes the house-strip lines from cited constants. Nothing is measured except the
baseline, and the page says so everywhere.

- **Input**: ZIP code, campus size in MW (presets 50, 100, 300, 1,000), cooling type (evaporative
  or closed loop), and a pin the user can drag on the map. ZIP resolves to a centroid from the
  Census ZCTA gazetteer, keyless. A ZIP is coarser than an address, but the same hygiene applies.
- **Engine**: `gather_ground` for the centroid, then arithmetic over `data/regions/us/constants.json`
  (same shape as `data/equivalences.json`: value, source page, verbatim quote). Lines: power as
  homes-equivalent and as a share of this utility's residential customers; bill, branching on the
  tariff table and shown as a range or as "shielded"; water by cooling type; land in acres and
  football fields; taxes and jobs as the other side, lowest confidence; noise from the pin's
  distance using the brief's existing distance model; and the N facilities already in the ring.
- **Models**: the numbers need no LLM, so a scenario is instant and ungated. One optional Spark
  paragraph interprets them, streamed afterwards behind the gate, with claims verified as usual.
- **Schema**: a separate `schema/scenario.schema.json` that reuses the brief's `$defs`
  (`house_line`, `claim`, `source`, `facility`, `price`, `tariff`) and adds `inputs`.
- **Cache**: keyed by inputs, stamped with the engine fingerprint, like briefs.

### 2. Share card that says it is AI-generated

X, Facebook and LinkedIn crawlers do not run JavaScript, so a `/b/{id}` link has no preview today.

- **Image endpoint** `GET /api/card/{id}.png`, 1200 by 630, rendered with Pillow in the Python
  service. No Chromium in the container. Cached beside the brief, stamped with the fingerprint.
- **Open Graph injection** in `app/static.py` for `/b/` and `/what-if/` routes: title,
  description, image and `twitter:card` written into the served `index.html`.
- **Three disclosure layers**, because platforms strip different things: a footer band in the
  pixels that survives every platform; C2PA content credentials and the IPTC digital source type
  in the file, which LinkedIn displays and X strips; and prefilled share text that says
  "AI-assisted, every claim cited" with the link. The same disclosure string lives in the brief
  (`card.disclosure`) so the DOM preview and the PNG agree.
- Share stays disabled until verification finishes, as today.

### 3. Home page

The address box stays the hero. Under it, a second panel, "Drop a data center on your town": ZIP,
MW slider, cooling toggle. Submit goes to `/what-if/{id}`, which reuses the map, the house strip
and the claims appendix. Animation is driven only by engine numbers so it never waits on a model:
the footprint grows with the slider, the existing flow lines run from the campus, counters tick,
a timeline scrubber fills the impact bars from announcement to energised. A persistent banner
reads "Hypothetical. Modelled, not measured." The pulse lines stay as they are.

### 4. Europe and India

PeeringDB and OpenStreetMap are already global, the models are region-neutral and the brief's
`unavailable` status lets a region ship before every provider exists. What is US-coupled:

| Provider | US today | Europe | India |
|---|---|---|---|
| Geocoder | Census | Nominatim (hosted) or Google Geocoding | Google Geocoding; India Post PIN centroids |
| Utility | HIFLD polygons | Per-country DSO GeoJSON, curated; Ireland is one DSO | State to DISCOM table, curated; Mumbai and Delhi have several |
| Prices | EIA-861M, monthly by state | Eurostat `nrg_pc_204`, semi-annual by country | State regulator tariff orders, annual, slabbed, curated |
| Tariff shield | `tariffs.json` by state | Connection policies (CRU Ireland), moratoria (NL) | HT industrial tariffs; the cross-subsidy surcharge flips the sign |
| Hearings | Granicus | Planning boards, council webcasts | Pollution control board public hearings, municipal corporations |
| Imagery | NAIP 1 m | National orthophotos where free, else Sentinel-2 10 m with a higher roof threshold | Sentinel-2 |
| Constants | EIA home, football field | Eurostat household consumption, litres, euros | Household consumption, litres, rupees, cricket ground |

A `Region` bundles implementations of the protocols the ground layer already defines, declares
which sections it can make `measured`, and owns its curated data under `data/regions/{id}/`. The
schema gains a `locale` block and region-neutral address fields. The edge country header the gate
already trusts picks the default region; a switch in the shell overrides it. Ireland first.

---

## Part 2. Low-level design

### A. Share images and Open Graph

#### A.1 Disclosure string in the brief

`app/brief/headline.py::derive_card` adds `card["disclosure"]`:

```
AI-assisted brief. Facts measured from public data; sentences drafted by Muse Spark and checked
by Muse Spark Open. {public_base_url}/b/{brief_id} · {generated_at date}
```

`schema/brief.schema.json` → `card.properties.disclosure: {type: string}` (optional, so cached
briefs stay valid). `web/src/types.ts` mirrors it. `ShareCard.tsx` renders it as the footer band.

#### A.2 Module `services/api/app/card/`

```
app/card/
  __init__.py
  spec.py        CardSpec and the two builders
  render.py      Pillow rasteriser
  provenance.py  XMP and optional C2PA
  fonts/         OFL fonts used by the web UI (shipped in the image; app/ is in the Dockerfile)
```

```python
# spec.py
@dataclass(frozen=True)
class CardSpec:
    kind: Literal["brief", "scenario"]
    title: str                 # card.title without the "Who's on my grid: " prefix
    lines: tuple[str, ...]     # card.lines, bill line dropped when `big` is shown (as ShareCard.tsx)
    big: str | None            # "+$9 to $14" from headline.ai_rent_range_usd_per_month
    big_caption: str | None    # "a month for a typical home, 2025 vs 2023 · modeled"
    footer: str | None         # card.footer (sources)
    disclosure: str            # card.disclosure
    hypothetical: bool         # scenario cards: banner "Hypothetical. Modelled, not measured."

def spec_from_brief(brief: dict[str, Any]) -> CardSpec: ...
def spec_from_scenario(scenario: dict[str, Any]) -> CardSpec: ...
def share_text(spec: CardSpec, url: str) -> str:
    """'{title}. {lines[0]} AI-assisted brief, every claim cited. {url}'"""
```

```python
# render.py
W, H = 1200, 630
INK, PAPER, SIGNAL = "#...", "#...", "#..."   # copied from web/src/index.css tokens

def render_png(spec: CardSpec) -> bytes:
    """Deterministic: same spec, same bytes (fixed fonts, no timestamps in the PNG)."""
```

Layout mirrors `ShareCard.tsx`: title top-left at 9% of width, wordmark top-right, lines
bottom-left in a 62% column, big number bottom-right in SIGNAL, sources footer at 2% from the
bottom, and a full-width disclosure band under it (dark on paper, 1.8% type). Text wraps with
`ImageDraw.textlength`. Scenario cards add a top band "HYPOTHETICAL · modelled, not measured".

```python
# provenance.py
IPTC_COMPOSITE_AI = "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"

def with_xmp(png: bytes, *, source_type: str, description: str, link: str) -> bytes:
    """Adds an iTXt chunk 'XML:com.adobe.xmp' with Iptc4xmpExt:DigitalSourceType,
    dc:description and a link. Always applied."""

def with_c2pa(png: bytes, *, settings: Settings) -> bytes:
    """Signs a C2PA manifest (c2pa.created, digitalSourceType as above, generator name and
    the model ids) when GRID_C2PA_CERT_PATH and the key from Key Vault are configured and
    the `c2pa` package imports. Otherwise returns png unchanged and logs once."""
```

X strips both on upload. The pixels are the guarantee; metadata is best effort and also meets
the EU AI Act Article 50 machine-readable marking when the EU region ships.

#### A.3 Card cache

`app/card/__init__.py::CardCache(directory)` with `path(kind, id) -> {dir}/{kind}/{id}.{fingerprint}.png`,
`get`, `put` (unique temp name then replace, as `BriefCache.put`). Settings: `cards_dir = "data/cards"`;
on Azure it lives under the `/mnt/grid` share like `data_dir`.

#### A.4 Router `app/routers/card.py`

| Route | Behaviour |
|---|---|
| `GET /api/card/{brief_id}.png` | `cache.get(brief_id)` without `current_only` so old links still render. 404 `brief_not_found`. Render in `asyncio.to_thread`. `Cache-Control: public, max-age=86400`, `ETag: "{fingerprint}-{brief_id}"`. |
| `GET /api/card/{brief_id}.json` | `CardSpec` plus `share_text`, `url`, `image_url`. The share menu reads this so text and image agree. |
| `GET /api/scenario-card/{scenario_id}.png` and `.json` | Same for scenarios. |

`brief_id` is validated against `^[0-9a-f]{16}$` before touching the filesystem.

#### A.5 Open Graph injection in `app/static.py`

`web/index.html` gains a marker inside `<head>`: `<!--og-->`, and the default site tags.

```python
_SHARE_ROUTES = re.compile(r"^(b|what-if)/([0-9a-f]{16})$")

def og_tags(meta: OgMeta) -> str  # html.escape on every value
def inject(index_html: str, tags: str) -> str  # replaces the marker once

@app.get("/{path:path}")
async def spa(path: str) -> Response:
    ... existing api/file handling ...
    m = _SHARE_ROUTES.match(path)
    if m and (meta := app.state.og.lookup(kind=m[1], id=m[2])):
        return HTMLResponse(inject(index_html, og_tags(meta)), headers={"Cache-Control": "no-cache"})
    return HTMLResponse(inject(index_html, og_tags(DEFAULT)), ...)
```

`OgMeta`: `title`, `description` (first card line plus " AI-assisted brief, every claim cited."),
`image` (absolute, from `settings.public_base_url`), `url`, `image_alt` (includes "AI-assisted"),
`type="article"`, `twitter:card="summary_large_image"`. `app.state.og` reads the brief and scenario
caches; a miss returns the default so the SPA shows its own not-found page. `index.html` is read at
mount time, not per request. New setting: `public_base_url: str = ""` (falls back to the request's
origin when empty, which is what local runs want).

#### A.6 Web

- `web/src/lib/api.ts`: `getCard(kind, id): Promise<CardInfo>`.
- `web/src/components/ShareMenu.tsx` `({ kind, id, disabled })`: fetches `CardInfo`; buttons
  X (`https://x.com/intent/post?text=&url=`), Bluesky (`https://bsky.app/intent/compose?text=`),
  Threads (`https://www.threads.net/intent/post?text=`), LinkedIn
  (`https://www.linkedin.com/sharing/share-offsite/?url=`), Facebook
  (`https://www.facebook.com/sharer/sharer.php?u=`), WhatsApp (`https://wa.me/?text=`), native
  share when `navigator.share` exists, copy link, download PNG (`<a download>` to the image URL).
  All intents open with `rel="noopener"`.
- `ShareCard.tsx`: adds the disclosure band and, for scenarios, the hypothetical band; otherwise
  unchanged. `BriefPage.tsx` swaps its Share button for `ShareMenu`, still disabled until
  `stage === 'done'`.

#### A.7 Tests

- `tests/test_card.py`: `spec_from_brief` on each fixture matches `card.lines` and the bill-line
  rule; `render_png` returns a 1200×630 PNG whose XMP chunk contains `DigitalSourceType`; two
  renders of one spec are byte-identical; router 200 for a cached brief, 404 otherwise, 422 for a
  malformed id.
- `tests/test_static.py`: `/b/{id}` for a cached brief carries `og:image`; a title with `<` is
  escaped; `/about` gets the default tags; `/api/…` still 404s from the SPA handler.

#### A.8 Build and deploy

`pyproject.toml` adds `pillow`; `c2pa-python` goes in an optional `provenance` group. Fonts sit
under `app/card/fonts/`, which the `.dockerignore` allow-list already includes via
`!services/api/app`. Bicep adds nothing for XMP-only; C2PA needs a cert and key in Key Vault,
loaded by the user-run secrets phase.

### B. Scenario engine

#### B.1 Data: `data/regions/us/constants.json`

Built as `data/scenario_constants.json`; step 5 (D.3) moved it to the US region's directory.

Same shape as `equivalences.json` (`{"_about", "constants": [{id, value, unit, as_of,
source_title, source_url, quote, checked}]}`). `app/scenario/constants.py::load()` merges
`equivalences.json` first, then this file, into `dict[id, Constant]`. Values are filled from the
page when curated; the ids and the kind of page are fixed here:

| id | unit | kind of source |
|---|---|---|
| `dc_load_factor` | fraction | LBNL 2024 US data center energy report or EPRI load study |
| `water_evaporative_l_per_kwh` | litres per kWh | LBNL 2024 water intensity, or a permitted facility's filing |
| `water_closed_loop_l_per_kwh` | litres per kWh | same |
| `us_home_water_gal_per_day` | gallons per household per day | EPA WaterSense ("more than 300 gallons") |
| `dc_acres_per_mw` | acres per MW | a county planning staff report with site acreage and MW |
| `dc_construction_months_lo`, `_hi` | months | industry survey or two permitted projects' timelines |
| `dc_permanent_jobs_per_100mw` | jobs | an economic impact statement, cited with its caveats |
| `dc_tax_usd_per_mw_year` | USD | Loudoun County budget: data center tax revenue over installed MW |
| `pjm_capacity_usd_per_mw_year` | USD | PJM's capacity clearing price × 365 (PJM utilities only; not a transmission cost) |
| `residential_allocation_lo`, `_hi` | fraction | the Harvard Electricity Law Initiative paper or a commission order |

As curated (step 2), several ids use a different kind of page, on purpose. The verifier reads HTML
and plain text only (`app/brief/fetch.py` reports a PDF as unfetchable), and the LBNL 2024 report,
the Harvard paper and the Loudoun budget are PDFs, so a quote from them could never be checked.
The substitutes are HTML pages that state the figure verbatim:

| id | substitute page | why it stands in |
|---|---|---|
| `dc_load_factor` | gridflexibility.fyi, citing Duke's 80% planning assumption and Dominion's measured 82% (Grid Strategies 2025) | a utility planning figure, the same quantity the LBNL/EPRI sources model |
| `water_evaporative_l_per_kwh` | an industry WUE explainer citing 1.8 to 1.9 L/kWh for evaporative systems | the LBNL water intensity is in the PDF; the low end is used |
| `water_closed_loop_l_per_kwh` | Microsoft's zero-water-for-cooling design | a permitted design's own statement |
| `dc_acres_per_mw` | a land-requirements guide's 1 acre per MW working rule (range 0.5 to 1.5) | no county staff report with both acreage and MW was found as HTML |
| `residential_allocation_lo` | EIA: residential share of US retail sales, 37.3% | how a cost lands on households when it is spread by energy sold |
| `residential_allocation_hi` | Maryland People's Counsel: $823 million of about $1.6 billion of data-center transmission cost to residential customers | an observed allocation of a data-center-driven cost |

The two allocation ends are two allocation methods (by energy sold, and as Maryland's transmission
cost was actually split), so the range brackets the method, not one measured quantity; the bill
line says "if PJM's capacity price ... were shared out like other costs" for that reason.
`dc_tax_usd_per_mw_year` is omitted: the only HTML figure found was an illustrative example (a
300 MW campus at a 1.0% rate), not a measured county figure, so the taxes block is null and the
ledger line shows jobs alone. Each row also carries `claim`, a sentence restating only what its
quote says (no derived value), which is the text of the constant's engine claim.

Each `Constant` exposes `.source(now_iso) -> dict` matching the schema's `source` def
(`title`, `url`, `retrieved_at` = `checked`, `quote`), so a constant can back a claim directly.
`_ENGINE_GLOBS` in `app/brief/cache.py` adds `data/scenario_constants.json` and
`schema/scenario.schema.json`; `.dockerignore` adds `!data/scenario_constants.json`. Since
step 5 both name `data/regions/` instead (D.3).

#### B.2 ZIP resolution and households

```python
# app/geocode.py
class ZctaCentroids:
    """Census Gazetteer ZCTA file (GEOID, INTPTLAT, INTPTLONG), downloaded once to
    data/ground/, loaded lazily. State and county come from the FCC area API the brief
    geocoder already falls back to."""
    async def locate(self, zip5: str) -> GeocodeResult | None
    # GeocodeResult(display="ZIP 20147, Loudoun County, VA", lat, lon, state, county,
    #               zip=zip5, matched=f"zip:{zip5}")
```

```python
# app/ground/census.py
@dataclass(frozen=True)
class Households:
    count: int
    source_url: str   # the ACS API call, table B11001_001E for the ZCTA
    source_title: str
    as_of: str        # "ACS 5-year 2023"

class AcsHouseholds:
    async def for_zcta(self, zip5: str) -> Households | None   # cached under data/ground/acs/

class FakeHouseholds: ...
```

Optional `census_api_key` setting. api.census.gov no longer answers without a key (a keyless
request is redirected to `missing_key.html`), so without a key, or when that call fails,
`AcsHouseholds` reads the same national table from data.census.gov's keyless table API. The
cited `source_url` is always the keyless data.census.gov page for the one ZCTA.

#### B.3 Module `services/api/app/scenario/`

```
app/scenario/
  __init__.py
  inputs.py      ScenarioInputs and the id
  constants.py   merged constants loader
  model.py       pure arithmetic, one function per line
  assemble.py    Scenario JSON from inputs, ground truth and constants
  interpret.py   the optional Spark paragraph and its claims
  pipeline.py    ScenarioService
  cache.py       ScenarioCache (BriefCache with a different directory and id field)
```

```python
# inputs.py
Cooling = Literal["evaporative", "closed_loop"]

@dataclass(frozen=True)
class ScenarioInputs:
    zip: str                       # ^\d{5}$
    mw: int                        # 10..2000
    cooling: Cooling
    pin: tuple[float, float] | None  # rounded to 3 decimals (~100 m) before id and storage

    def scenario_id(self) -> str:
        """sha256 of 'zip|mw|cooling|lat|lon', first 16 hex. Nothing else derived from the
        inputs is logged."""
```

```python
# model.py  (every function returns a Result: value(s), basis sentence, constants used)
@dataclass(frozen=True)
class Result:
    value: float | tuple[float, float] | None
    basis: str                     # "100 MW × 0.8 × 8,760 h ÷ 10,791 kWh per home (2022)"
    constants: tuple[Constant, ...]
    confidence: float

def annual_gwh(mw: int, c: Constants) -> Result
def homes_equivalent(gwh: float, c: Constants) -> Result
def share_of_utility_homes(homes: float, utility: Utility | None) -> Result | None
def water_gal_per_day(mw: int, cooling: Cooling, c: Constants) -> Result
def water_homes_equivalent(gal_per_day: float, c: Constants) -> Result
def land_acres(mw: int, c: Constants) -> Result
def football_fields(acres: float, c: Constants) -> Result
def bill_outcome(tariff: TariffEntry | None, utility: Utility | None, mw: int, c: Constants) -> BillOutcome
def taxes_usd_per_year(mw: int, c: Constants) -> Result        # range ±50 %
def jobs(mw: int, c: Constants) -> Result
def construction_months(c: Constants) -> Result
def noise_at(distance_km: float) -> Result                     # factored out of headline.noise_house_line
```

```python
@dataclass(frozen=True)
class BillOutcome:
    kind: Literal["shielded", "partial", "exposed", "unknown"]   # from TariffEntry.lead
    range_usd_per_month: tuple[float, float] | None
    basis: str
    confidence: float   # 0.3 when exposed; the tariff page's confidence when shielded
```

Exposed formula, stated on the page: `mw × pjm_capacity_usd_per_mw_year × allocation ÷
utility.customers ÷ 12`, evaluated at `allocation_lo` and `allocation_hi`. The price is PJM's
capacity price, not a transmission cost, so it is used only when the utility's EIA-861
`BA Code` is `PJM`; elsewhere, or with no utility customer count, the kind is `unknown` and
the line says so.

```python
# assemble.py
def assemble_scenario(
    inputs: ScenarioInputs, geo: GeocodeResult, truth: GroundTruth | None,
    households: Households | None, c: Constants, *, scenario_id: str, now_iso: str,
) -> dict[str, Any]
```

Builds the Scenario JSON (B.4). Each strip line is a `house_line` with `status: "modelled"`,
`confidence` from the `Result`, and `sources` = the constants' sources plus the ground source it
leans on (utility page for the share line, tariff page for the bill line). Each line also yields
one engine claim per constant: `text` = the constant's curated `claim` (only what the quote says;
the quote itself when there is no `claim`), `source` = the constant's page with its quote,
`verdict: "unchecked"`. The basis sentence, which carries the engine's derivation (×365, ÷100 and
so on), stays on the line and in `impact.*.basis`, never in a claim attributed to the page; a
constant used by several lines yields one claim. The verifier then fetches each page and finds the quote exactly
as it does for briefs, so the arithmetic is checkable without a model drafting anything.
Baseline facilities reuse `assemble._facility` and `_facility_claim`.

```python
# pipeline.py
@dataclass(frozen=True)
class ResolvedScenario:
    inputs: ScenarioInputs
    geo: GeocodeResult
    scenario_id: str
    cached: dict | None

class ScenarioService:
    def __init__(self, *, settings, zips: ZctaCentroids, ground: Ground | None,
                 households: AcsHouseholds | FakeHouseholds, cache: ScenarioCache,
                 fetcher: Fetcher, draft_provider: LLMProvider | None,
                 verify_provider: LLMProvider | None) -> None
    async def resolve(self, inputs: ScenarioInputs) -> ResolvedScenario      # raises ZipNotFound
    async def compute(self, resolved: ResolvedScenario) -> dict               # engine only, no tokens
    async def interpret(self, scenario_id: str, progress: Progress | None) -> dict
        # one Spark call with a strict schema {summary, claims[]}, verify_claims on its claims,
        # write `interpretation` into the cached scenario, return it
```

`compute` runs `gather_ground(geo, ground)` and `households.for_zcta`, assembles, validates
against the scenario schema, verifies the constant claims (cheap: page fetch plus verifier; skip
to `unchecked` when the verifier is off), caches. `Inflight` is reused keyed by `scenario_id`.

```python
# interpret.py
INTERPRET_PROMPT  # "Here is a modelled scenario... write 3 sentences a resident would read.
                  # Say it is hypothetical. Cite only the pages in the facts block."
async def draft_interpretation(provider, scenario: dict) -> DraftResult | SectionFailure
```

#### B.4 Schema `schema/scenario.schema.json`

```jsonc
{
  "$id": "scenario.schema.json",
  "required": ["scenario_id", "generated_at", "engine", "kind", "disclosure", "inputs", "place",
               "baseline", "impact", "lines", "claims", "card"],
  "properties": {
    "scenario_id": {"type": "string"},
    "generated_at": {"type": "string", "format": "date-time"},
    "engine": {"type": "string"},
    "kind": {"const": "scenario"},
    "disclosure": {"const": "Hypothetical. Modelled, not measured."},
    "inputs": {"zip", "mw", "cooling", "pin": {"lat", "lon"}},
    "place": {"display", "state", "county", "zip", "lat", "lon",
              "households": {"count", "source": {"$ref": "brief.schema.json#/$defs/source"}} | null},
    "baseline": {
      "facilities": [{"$ref": "brief.schema.json#/$defs/facility"}],
      "facility_count": "integer",
      "utility": {"name", "kind", "customers", "source"} | null,
      "price": {"$ref": "brief.schema.json#/$defs/price"} | null,
      "tariff": {"$ref": "brief.schema.json#/$defs/tariff"} | null
    },
    "impact": {
      "power": {"gwh_per_year", "homes_equivalent", "share_of_utility_homes": number | null},
      "water": {"gal_per_day", "homes_equivalent"} | null,
      "land": {"acres", "football_fields"},
      "bill": {"kind": enum, "range_usd_per_month": [lo, hi] | null},
      "taxes": {"range_usd_per_year": [lo, hi]} | null,
      "jobs": {"permanent"} | null,
      "noise": {"distance_km", "db_at_pin": number | null},
      "timeline": {"construction_months": [lo, hi]}
    },
    "lines": {"type": "array", "maxItems": 7,
              "items": {"$ref": "brief.schema.json#/$defs/house_line"}},   // every status "modelled"
    "interpretation": {"status": {"const": "reported"}, "text", "model", "confidence",
                       "draft": boolean} | null,
    "claims": [{"$ref": "brief.schema.json#/$defs/claim"}],
    "card": {"title", "lines", "footer", "disclosure"}
  }
}
```

`app/schema.py` loads both schemas into one `referencing` registry so the `$ref`s resolve; the
`claim.section` enum gains `"scenario"`. `web/src/types.ts` gains `Scenario`, `ScenarioInputs`,
`Impact`.

#### B.5 Router `app/routers/scenario.py`

| Route | Gate | Behaviour |
|---|---|---|
| `POST /api/scenario` `{zip, mw, cooling, pin?}` | none; `same_site_post`; global soft cap `scenario_global_day` (default 2,000) | `resolve` → `compute`. 404 `zip_not_found`. 422 on range errors. Returns the scenario. |
| `GET /api/scenario/{id}` | none | From cache, any engine, so links keep working. |
| `POST /api/scenario/{id}/interpret` | signed in, quota charged once per `(user, id)` via `Gate.charge(user, f"scenario:{id}")` | NDJSON: `{stage:"drafting"}` → `{stage:"verifying", verified, claims}` → `{stage:"done", scenario}`. Idempotent: an existing interpretation returns `done` immediately and charges nothing. |

`Gate` gains `admit_scenario(user) -> User` (sign-in and quota only; no address allow-list).
Usage rows hold the subject, email and `scenario:{id}`, never the ZIP.

Settings added: `scenarios_dir = "data/scenarios"`, `scenario_global_day = 2000`,
`census_api_key = ""`. `main.py::default_service` builds `ScenarioService` beside `BriefService`
and stores it as `app.state.scenarios`.

#### B.6 Tests and eval

- `tests/test_scenario_model.py`: with a fake constants table, 100 MW at 0.8 load factor is
  700.8 GWh and about 64,900 homes at 10,791 kWh; closed loop uses less water than evaporative;
  `bill_outcome` is `shielded` with a protecting tariff and `exposed` with `none_found`.
- `tests/test_scenario_assemble.py`: schema-valid output with fakes; every line `modelled`; every
  claim has a quote; no line mentions a facility the ground truth does not list.
- `tests/test_scenario_router.py`: POST without sign-in succeeds; interpret without sign-in is
  401; a second interpret does not charge; malformed ZIP is 422.
- `tests/test_scenario_cache.py`: same inputs give the same id; pins 30 m apart give the same id;
  a fingerprint change regenerates.
- `eval/scenarios.json`: five ZIPs (Ashburn, New Albany, Tucson, Council Bluffs, Bellevue) with
  expected baseline facility counts and tariff leads; `eval/run_eval.py --scenarios`.

### C. Home page and what-if page

#### C.1 Routing and state

- `web/src/main.tsx`: add `<Route path="/what-if/:key" element={<ScenarioPage />} />`.
- `web/src/lib/api.ts`: `createScenario(inputs): Promise<Scenario>`, `getScenario(id)`,
  `streamInterpretation(id, onEvent)`. Factor the NDJSON reader out of `streamBrief` into
  `readNdjson(response, onLine)` and use it from both.
- `web/src/lib/live.ts`: add `setLiveScenario` / `useLiveScenario` beside the brief ones, so the
  page opens from navigation state before the fetch, as the brief page does.

#### C.2 Components

| Component | Props | Notes |
|---|---|---|
| `WhatIfPanel.tsx` | `{ onSubmit(inputs) }` | ZIP input (`inputMode="numeric"`, 5 digits), `MwSlider`, cooling toggle. Validates client-side; shows the engine's 404 text for an unknown ZIP. |
| `MwSlider.tsx` | `{ value, onChange }` | Log-scale range 20–2,000 MW with snap points at 50, 100, 300, 1,000; the label shows homes-equivalent live from `us_home_kwh_per_year`, fetched once from `/api/pulse` constants. |
| `ScenarioPage.tsx` | route param | Loads the scenario; owns the controls (changing MW or cooling calls `createScenario` debounced 300 ms and `navigate(..., {replace: true})`). |
| `HypotheticalBanner.tsx` | `{ text }` | Sticky, modelled colour, always visible. |
| `ScenarioMap.tsx` | `{ center, pin, acres, facilities, onPinMove }` | Leaflet. Footprint is a square of `acres` centred on the pin; `useAnimatedNumber(acres, 600ms)` drives its side. Flow lines from the pin to the ZIP centroid and to the existing facilities reuse the dashed-line layer from `MapView`. Draggable marker; drop fires `onPinMove`. |
| `ImpactCounters.tsx` | `{ impact }` | Homes, gallons a day, acres, bill range. Each counter animates with `useAnimatedNumber`; each carries the modelled tag and a tap-to-see-basis popover. |
| `Timeline.tsx` | `{ months: [lo, hi], impact }` | Scrubber 0–100 across announced → permitted → under construction → energised; power, water and bill bars fill to their final values at the energised mark; land fills during construction. Pure client-side. |
| `HouseStrip` (existing) | `{ lines }` | Unchanged. |
| `Claims` (existing) | `{ claims }` | Unchanged; section label "scenario". |
| `ShareMenu` (A.6) | `kind="scenario"` | Enabled once `claims` are all checked or the verifier is off. |

`MapView.tsx` is refactored into a thin `BriefMap` wrapper over a generic `GridMap` that takes
`{ center, markers, lines, polygons }`, so `BriefPage` is unchanged and `ScenarioMap` shares the
layers. `prefers-reduced-motion` disables counters, flows and the footprint transition.

#### C.3 Home page

`Home.tsx` keeps the address form, sign-in and test addresses as the first panel. A second panel
renders `WhatIfPanel`; on submit it calls `createScenario`, stores the result with
`setLiveScenario`, and navigates. No sign-in is required and the busy state shows a spinner only,
since the response is sub-second once the area's ground data is cached and a few seconds otherwise.
The pulse lines are unchanged.

### D. Regions

#### D.1 `app/regions/`

```python
@dataclass(frozen=True)
class Locale:
    country: str          # ISO 3166-1 alpha-2
    currency: str         # USD, EUR, GBP, INR
    units: Literal["us", "metric"]
    language: str         # BCP 47, for prompts and hearing transcription

@dataclass
class Region:
    id: str                         # "us" | "eu" | "in"
    locale: Locale
    geocoder: Geocoder
    ground: Ground
    constants: dict[str, Constant]  # data/regions/{id}/constants.json merged over the shared file
    coverage: frozenset[str]        # section ids this region can make `measured`
    postal_pattern: re.Pattern      # for the what-if input and the id prefix
    test_set: Path                  # eval/{id}/addresses.json

def registry(settings: Settings) -> dict[str, Region]           # only ids in settings.regions
def region_for(*, explicit: str | None, country_header: str | None, default: str) -> Region
```

`settings.regions = "us"` enables regions; `GRID_REGIONS=us,eu` enables Europe on the same image.

As built in step 5: `Region` holds `make_ground(settings)` rather than a `Ground`, so a test
that injects a service never leaves a second, unused ground on the region; the service's
`ground` is the one a brief reads. `Region` also carries `label`, `countries` (the header
codes that map to it), `data_dir` and `resolved`. `region_for(regions, *, explicit,
country_header, default)` takes the registry; the header counts only when
`GRID_ALLOWED_COUNTRIES` is set, and a blank `region` counts as absent.
`GRID_DEFAULT_REGION` (default `us`) names the region a request without one gets. The US test
set stays at `eval/addresses.json` until step 6 adds `eval/ie/`.

#### D.2 Protocol changes in `app/ground`

| Protocol | Today | Change |
|---|---|---|
| `Geocoder.geocode` | `GeocodeResult(state, zip)` | `GeocodeResult` adds `country`, `region_code`, `postal_code`; `state` and `zip` stay as read-only aliases during migration. |
| `UtilityProvider` | HIFLD point-in-polygon, then `_choose_utility` disambiguates with EIA data | Disambiguation moves inside `HifldUtility.locate(geo)`; `gather_ground` calls `ground.utility.locate(geo)` only. New `GeoJsonUtility(path)` and `StateMapUtility(path)`. |
| `PriceProvider.series(state)` | state code | `series(jurisdiction)`; `PriceSeries` adds `currency`, `granularity: monthly \| semiannual \| annual`. New `EurostatPrices` (`nrg_pc_204`, band DC, all taxes), `CuratedPrices(path)`. |
| `Tariffs.match(state, utility)` | state | `match(jurisdiction, utility)`; `TariffEntry.state` → `jurisdiction`. The table moves to `data/regions/{id}/tariffs.json`. |
| `HearingIndex`, `ImageryIndex` | file paths | Unchanged protocols; paths come from the region. Indexers gain `--source` (`granicus`, `publici`, `planning-pdf`, `spcb-minutes`) and `--provider` (`naip`, `sentinel2`, `pdok`, `ign`) with `min_roof_acres` per provider. |

New geocoders: `NominatimGeocoder(base_url, user_agent, countrycodes)` for a hosted or
self-hosted instance (the public instance's policy rules out production use),
`GoogleGeocoder(key)` with a server key separate from the browser key, `PinCentroids` for
India Post PIN input in the what-if panel.

#### D.3 Curated data layout

```
data/regions/us/   tariffs.json  facilities.json  constants.json  hearings/  perception/
data/regions/eu/   tariffs.json  facilities.json  constants.json  utilities/ie.geojson  utilities/uk.geojson  prices/  hearings/  perception/
data/regions/in/   tariffs.json  facilities.json  constants.json  discoms.json  prices.json  hearings/  perception/
```

Every curated row keeps the `url`, `title`, `quote` triple. `_ENGINE_GLOBS` adds
`data/regions/**`. `.dockerignore` adds `!data/regions` and excludes imagery binaries as today.
As built, the globs name only JSON and GeoJSON under `data/regions/`, so audio and imagery
tiles that exist locally but not in the image never make the two fingerprints differ.

#### D.4 Schema

- `address`: add `country`, `region_code`, `postal_code`; keep `state`, `zip` optional so cached US
  briefs validate.
- New top-level `locale` (`country`, `currency`, `units`, `language`), optional.
- `price`: add `currency`, `granularity`.
- `web/src/lib/format.ts`: `fmtMoney(v, currency)`, `fmtDistance(km, units)`,
  `fmtVolume(l, units)`, `fmtArea(acres, units)`.

#### D.5 Ids, routing and the gate

- `brief_id_for(matched)` is unchanged for the US. Other regions hash `f"{country}|{matched}"`
  so identical strings in two countries never collide and existing US links stay valid.
- `POST /api/brief` and `/api/brief/stream` accept optional `region`; the router resolves it
  with `region_for(explicit, header, default)` and builds the `BriefService` per region from a
  registry (`app.state.services[region.id]`). `GET /api/health` returns `region` and
  `regions` so the UI can show the switch.
- The gate's allow-list unions every enabled region's test set. Quotas are unchanged.
- `/api/pulse?region=eu` filters the PeeringDB snapshot by the region's country list; the
  equivalence lines use the region's constants.

#### D.6 Web

- `Shell.tsx`: a region switch (flag-free text: "US · Europe · India"), stored in `localStorage`
  with the server's default as the fallback.
- `AddressInput.tsx`: Places `componentRestrictions: { country }`, placeholder per region.
- `TestAddresses.tsx`: the region's examples from `/api/health`.
- `Sections.tsx`, `HouseStrip.tsx`, `ShareCard.tsx`: numbers through `format.ts` with the
  brief's `locale`.
- `About.tsx`: a privacy paragraph per region (GDPR lawful basis and retention for the EU, DPDP
  for India). New setting `brief_ttl_days` (0 = keep) applied by `BriefCache.get` for non-US
  regions.

#### D.7 Deployment

One image, `GRID_REGIONS` chooses what it serves. EU data residency, when wanted, is a second
Container App in `westeurope` with its own storage and `GRID_REGIONS=eu`, routed by host. Nothing
in Bicep changes for the first EU rollout.

#### D.8 Tests

- `tests/test_regions.py`: registry honours `GRID_REGIONS`; `region_for` prefers explicit, then
  header, then default; an unknown explicit region is 422.
- `tests/test_geojson_utility.py`: point-in-polygon on a two-polygon fixture, overlap resolved
  by customer count.
- `tests/test_eurostat.py`: parser on a saved JSON-stat response yields `semiannual` series in
  EUR with the right 24-month lag.
- `tests/test_schema_compat.py`: every brief under `fixtures/` and `data/briefs.pre-step4`
  still validates after the address and locale changes.
- Ireland fixture brief (Dublin 15, ESB Networks, CRU connection policy) under `fixtures/`.

---

## Build order and size

| Step | Work | Size |
|---|---|---|
| 1 | A: card PNG, XMP, OG injection, share menu, disclosure string | 1 to 2 days |
| 2 | B.1 to B.6: constants file, ZIP centroids, ACS households, model, assemble, router, tests | 2 to 3 days |
| 3 | C: what-if panel, scenario page, map refactor, counters, timeline | 2 to 3 days |
| 4 | B interpret endpoint behind the gate; C2PA signing | 1 day |
| 5 | D.1 to D.5 with the US as the only region; no behaviour change; schema compat tests | 2 days |
| 6 | Ireland: geocoder, ESB GeoJSON, Eurostat prices, CRU tariff row, one planning hearing, fixture, eval rows | 3 to 4 days |
| 7 | UK, Netherlands, Germany; then Mumbai, Hyderabad, Chennai with DISCOM and tariff-order rows | per region |
