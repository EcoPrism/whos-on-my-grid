# Who's on my grid

A US address in, a checked brief out: which data centers are on your local grid, what is being
built, what your bill did, whether a tariff shields you, and what was said at the last hearing.
Read `README.md` first, then `docs/build-log.md` for what was built when and why.

## Layout

- `services/api` — FastAPI, Python 3.13, `uv`. `app/brief` makes a brief (pipeline, assemble,
  verify); `app/ground` is the engine's data (facilities, utility, prices, tariffs, imagery and
  hearing indexes); `app/perception` and `app/hearings` are offline indexers.
- `web` — Vite + React + TypeScript. `src/types.ts` mirrors `schema/brief.schema.json`.
- `data/` — curated JSON that is committed (`tariffs.json`, `facilities.json`, `hearings/`,
  `perception/`) and caches that are not (`briefs/`, `ground/`).
- `eval/` — the 30-address test set and `run_eval.py`.

## Commands

```
cd services/api && uv run pytest -q && uv run ruff check app tests && uv run ruff format --check app tests
cd web && npx tsc -p tsconfig.app.json --noEmit
```

## Rules that matter here

- Never read or print values from `services/api/.env` or `web/.env`. Keys are the user's.
- Addresses are personal data: never log one, never write one to disk outside the brief itself.
- Every engine claim cites a page the verifier can fetch, with a verbatim quote from that page.
  A claim must say only what its cited page shows; distance and counts are the engine's arithmetic.
- Facts from data are `measured`; a model's sentences are `reported` or `modelled`, and the
  section says which. Do not promote a model's guess to a measured status.
- Hearing recordings come from the official archive only, never from video platforms.
- The brief cache is stamped with an engine fingerprint (`app/brief/cache.py`); a code or
  curated-data change regenerates briefs on request. No manual cache clearing is needed.
- Long heredocs break in this environment's bash and halve backslashes. Write scripts to the
  scratchpad with the Write tool and run them with `python`.
