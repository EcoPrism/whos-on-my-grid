# Who's on my grid

A US address in, a checked brief out: which data centers are on your local grid, what is being
built, what your bill did, whether a tariff shields you, and what was said at the last hearing.
Read `README.md` first, then `docs/build-log.md` for what was built when and why.

## Layout

- `services/api` — FastAPI, Python 3.13, `uv`. `app/brief` makes a brief (pipeline, assemble,
  verify); `app/ground` is the engine's data (facilities, utility, prices, tariffs, imagery and
  hearing indexes); `app/perception` and `app/hearings` are offline indexers.
- `web` — Vite + React + TypeScript. `src/types.ts` mirrors `schema/brief.schema.json`.
- `data/` — curated JSON that is committed (`equivalences.json`, shared, and per region under
  `data/regions/<id>/`: `tariffs.json`, `facilities.json`, `constants.json`, `hearings/`,
  `perception/`; the US is `data/regions/us/`) and caches that are not (`briefs/`, `ground/`).
- `eval/` — the 30-address test set and `run_eval.py`. `eval/addresses.json` is also the sign-in
  gate's allow-list: those addresses run without an account.
- `services/api/app/auth` — the sign-in gate (`gate.py`), Google id_token check, session cookie,
  usage store (memory or Azure Table). `app/static.py` serves `web/dist` when it exists.
- `infra/` and `scripts/deploy.ps1` — one resource group on Azure Container Apps; `docs/deploy.md`
  is the runbook. `Dockerfile` builds from the repo root and keeps the repo layout (the engine
  fingerprint hashes it).

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
  section says which. Do not promote a model's guess to a measured status. The page shows the
  four statuses as From the data / Written by AI, checked / Our estimate / Not public, from
  `web/src/lib/words.ts` only; the schema values never change.
- Hearing recordings come from the official archive only, never from video platforms.
- The gate guards only new briefs. Usage rows hold a subject, an email and a brief id, never an
  address. Home-page figures come from `data/equivalences.json` with a source page and quote.
- Secret values stay out of Bicep, the console and the chat: `scripts/deploy.ps1 -Phase secrets`
  is run by the user and pipes `.env` values into Key Vault.
- The brief cache is stamped with an engine fingerprint (`app/brief/cache.py`); a code or
  curated-data change regenerates briefs on request. No manual cache clearing is needed.
- Long heredocs break in this environment's bash and halve backslashes. Write scripts to the
  scratchpad with the Write tool and run them with `python`.
