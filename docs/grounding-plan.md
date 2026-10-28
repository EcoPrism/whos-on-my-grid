# Grounding plan: engine-owned facts, Spark-written sentences

Written 2026-10-27 against the 30-address test set in `eval/addresses.json`. Baseline run
(`eval/runs/baseline`, agent mode as committed in 07f67da): **4 / 30 pass**. The four passes are
the zero-facility rows (Social Circle, Kuna, Honolulu, San Diego), which pass because the brief
says nothing. Per dimension: grid 7/30, bill 19/30, protection 26/30, strip 30/30, signatures 25/30.

## What the baseline shows

1. **Existence claims from memory fail everywhere.** 23 of 26 rows with facilities expected report
   zero. Ashburn, the densest cluster on earth, comes back "On your grid unavailable". Spark names
   no operator on any row. This is the Bellevue failure the reviewer caught, times 23.
2. **Spark is too verbose for its own token budget.** 67 of 180 section drafts failed, 57 of them
   On your grid and Your bill, all `finish_reason=length` at 6,144 tokens. Sections that did land
   ran 3,500–5,600 completion tokens. Half the "no bill number" failures are this, not knowledge.
3. **The bill number is stale or absent.** Where a price landed it was a 2024–25 figure presented
   as now (Bellevue +$13 vs about +$24 from the current EIA series). 11 rows have no number at all.
4. **Serving utility is never structured.** `address.utility` is null on all 30; the utility
   appears only in prose, so the UI never says "served by …" and Spark drafts tariff and bill text
   without knowing who sends the bill.
5. **Band ignores facilities.** Bozeman and Key West get `band: high` from a $10 statewide price
   rise with no facility within fifty miles. The negative controls fail on tone.
6. **Protection is generic.** 26/30 pass only because the oracle accepts `unknown` almost
   everywhere. Where a real tariff exists (Virginia GS-5, AEP Ohio data-center tariff) Spark says
   `unknown` with no name or docket.
7. **Status vocabulary cannot say "rejected".** Tucson's Project Blue (voted down Aug 2025) has no
   legal representation: the facility status enum is live / under_construction / announced.
8. **Verification is vacuous.** 0–3 claims supported per brief; the rest unverifiable because Spark
   cites homepages (pse.com, kingcounty.gov, EIA index pages) that contain nothing to check.

## The fix: `BRIEF_SOURCE=full`, ground truth first

The architecture the README already names for step 5. Facts that can come from data come from
data; Spark reads the data block in its prompt and writes sentences, codenames, attributions and
politics. The verifier then has real pages to check.

### Providers (`services/api/app/ground/`)

| Fact | Source | Access | Status |
|---|---|---|---|
| Facilities within 5 mi | PeeringDB `api/fac` (US snapshot, 1,378 sites with coordinates) + OpenStreetMap via Overpass (`telecom=data_center`, `building=data_center`, `construction=data_center`, `industrial=data_center`) | no key; PeeringDB snapshot cached 7 days under `data/`; Overpass per brief on `overpass.openstreetmap.fr` (the only mirror reachable from this network) | probed: Ashburn 208 OSM elements, Quincy 33, Altoona 9, New Albany 37, Bellevue 2 via PeeringDB |
| Serving utility | HIFLD Electric Retail Service Territories, point-in-polygon | ArcGIS FeatureServer query, no key | probed: Quincy → PUD No 2 of Grant County correct; coverage gaps on the services6 copy, other mirrors under test; falls back to null |
| Residential price, statewide | EIA-861M `sales_revenue.xlsx` (monthly, by state, residential revenue / sales / customers) | no key; 2.3 MB workbook cached 30 days | probed: data through August 2026 |
| Residential price, this utility | EIA-861 annual `Sales_Ult_Cust_YYYY.xlsx` (one row per utility and state), joined on the EIA utility number that HIFLD carries as `id`; latest two calendar years available, bundled service only | no key; two 4.5 MB zips cached | probed: Grant County PUD 5.6→6.0¢ while Washington statewide went 11.6→14.2¢, which is the Quincy counter-narrative |
| Typical household kWh | same workbooks: residential sales ÷ customers | derived | — |
| Utility disambiguation | EIA-861 `Service_Territory_YYYY.xlsx` (utility → counties) and its customer counts | same zips | HIFLD polygons overlap (Farmers EC over Oncor in Dallas, FPL over Keys Energy in Key West); keep candidates that report the address's county, then most customers |
| Large-load tariffs | `data/tariffs.json`, hand-curated commission orders and statutes with official URLs | in repo | the verifier fetches each URL like any other claim |

Clustering: OSM buildings sharing an operator within 500 m become one campus entry ("Microsoft,
9 buildings"); unnamed buildings merge into a PeeringDB site within 150 m when one exists, else
list as a cluster with operator "not recorded in OpenStreetMap". Each entry carries its source
URL (`openstreetmap.org/way/…`, `peeringdb.com/fac/…`) so a claim about it is checkable.

Price: rate_now is the trailing-12-month average residential price, rate_then the trailing-12
ending 24 months earlier; window 24 months; typical kWh from the state's own sales ÷ customers.
Status `modelled` (the dollar figure is state average × typical usage), confidence 0.85, source
the EIA-861M page.

### Spark's role after grounding

- **On your grid** gets the facility list. It writes the summary and may add MW, codename and
  operator-behind-codename for a listed facility, each as a claim. It cannot add or remove a
  facility: the assembler takes the engine's list and merges only those fields by name.
- **Coming** gets OSM `construction=data_center` entries as under_construction. Spark adds
  announced, permitted and rejected campuses from its knowledge, each as a claim. New facility
  status `rejected` (schema, UI grey) so a voted-down project can be shown as such.
- **Your bill** gets the EIA numbers, the utility's own series first and the statewide monthly
  series as context. Spark writes the summary around them and supplies the attribution quote (or
  null). The price block is the engine's; `price.as_of` labels the period so annual utility data
  is never read as "now".
- **Protection** takes the tariff table's entry for this utility when one exists (status, name,
  docket, whether it shields households, the lead word), with Spark's claims kept for the verifier.
- **Protection** and **Hearing** get the serving utility and state. Still Spark knowledge, with
  the prompt asking for the tariff name and docket when a real case exists.
- **At your house** gets the nearest facilities by name and distance so water, noise and tax lines
  anchor to real buildings ("the three facilities near you do not publish water use"). With no
  facility listed, impact lines are dropped by the assembler unless they say "not known".
- The **noise line** becomes engine-written like the bill line: nearest facility, its distance,
  what distance implies, "no sound measurement is public". Modeled, low confidence, the
  facility's source URL.
- **Band** considers facilities: no facility within five miles caps the band at `low`
  (or `medium` when the price rise is large), whatever the state price did.

### Token budget

Prompt caps: at most 8 claims per section, claims under 200 characters, summary two or three
sentences, no repetition of the data block. `GRID_LLM_MAX_TOKENS` default raised to 8192.

### Order of work

1. `app/ground/`: `facilities.py` (PeeringDB + Overpass + clustering), `utility.py` (HIFLD),
   `prices.py` (EIA-861M), `types.py`, with `Fake*` providers for tests and a `GroundTruth`
   bundle the pipeline gathers in parallel with geocoding.
2. Schema: facility status `rejected`; `source_mode` gains `full`; `address.utility` filled.
3. Pipeline, prompts, assembler, headline: data block in prompts, engine-owned facilities, price,
   utility, band, noise line, impact-line filter.
4. UI: `rejected` status in types, map color and section table; nothing else changes.
5. Tests: provider parsers on fixtures, clustering, assembler merge rules, band rule, impact-line
   filter; existing suite stays green.
6. Rerun `eval/run_eval.py`; iterate on prompts and merge rules until the test set is as green as
   the data allows. Hearing stays informational: no source for minutes exists in this step.

### What this cannot fix yet

- Hearing hooks (the Prince William Digital Gateway fight, Loudoun zoning) need indexed minutes:
  step 4. Manassas fails the test set on exactly this and nothing else.
- Campuses that exist only in news (Project Blue in Tucson, voted down August 2025; New Albany's
  current construction, which OpenStreetMap has not tagged) depend on Spark's memory, which does
  not hold them. Both rows fail on that alone. A permit or news source is the fix, not a prompt.
- MW is not in PeeringDB or OSM; the brief shows load only where Spark cites a source for it.
- Operators of buildings OpenStreetMap maps without an operator tag (Apple's Maiden campus is
  "2 unnamed data-center buildings") depend on Spark naming them from the facts block.

### What the test set got wrong

Three oracle rows assumed a campus inside the ring that the map puts outside it: Google's Council
Bluffs campus is about 13 km from the Broadway pin, Meta's Eagle Mountain campus 11.5 to 12.3 km
from Pony Express Parkway, Meta's Huntsville campus about 13 km from Wynn Drive. The rows were
corrected with a note; the product's answer ("none within five miles, nearest colocation sites
listed") is the right one. Tucson's "live near zero" missed three small colocation sites in
PeeringDB. A "nearest campus beyond the ring" line would make these briefs more useful and is a
natural next step.
