# Ireland (`ie`) curated data

Hand-curated, committed, and read by the engine for the `ie` region
(`app/ground/__init__.py` `get_ground_ie`, `IE_DATA_DIR`). The same rules as the US
files apply: every row names a page the verifier can fetch and quotes it verbatim.

| File | What it holds |
|---|---|
| `constants.json` | `ie_home_kwh_per_year` (CRU typical consumption, the bill's kWh figure) and `ie_dc_share_metered_electricity` (CSO, for the pulse line). |
| `tariffs.json` | One row: the CRU's December 2025 connection policy for new data centres (`kind: connection_policy`, `protects_households: false`, its stated aim is grid constraints, security of supply and renewable targets). |
| `hearings/sources.json` | Planning authorities (South Dublin, Fingal) and the An Coimisiún Pleanála decision on Google's Grange Castle expansion (PL06S.320852). Decisions are matched by distance, not by authority. |
| `facilities.json` | No operator overrides yet; `peeringdb_use_org_name` lists PeeringDB facility ids whose name field is shown as the organisation's name instead. |
| `utilities/ie.geojson` | ESB Networks' service area: one Feature, a MultiPolygon. |

## The ESB Networks boundary

`utilities/ie.geojson` is the union of the four provinces from Tailte Éireann,
"Provinces - National Statutory Boundaries - 2019 - Generalised 20m" (ArcGIS item
`1b341039d3344c74b95293012312f44d`). Ulster in that dataset is the three Republic
counties, so Northern Ireland is outside by construction. Simplified at 0.002 degrees,
islets of 0.00007 deg² or less dropped, coordinates to 5 decimals (about 229 KB).

Attribution: **© Tailte Éireann**, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Generalised boundaries,
for reference purposes only; the file is a simplified derivative.

Rebuild (network to services-eu1.arcgis.com; never substitute another boundary):

```
cd services/api
uv run --group index python scripts/build_ie_boundary.py
```

The script checks Dublin, Cork, Galway, Dundalk, Clones and Lifford fall inside and
Belfast, Derry, Strabane and Newry outside before it writes the file.

## Checked pages

`services/api/tests/fixtures/pages/*.txt` hold a short text window (the page's text
around the quote, made with the app's `html_to_text`) of every cited page, fetched
2026-10-29. `tests/test_ie_data.py` checks each quote against its window. Raw HTML is
never committed: the planning case pages name private parties.
