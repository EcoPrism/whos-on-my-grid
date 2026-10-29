# One image: the web app built by Node, served with the API by Python.
# Build from the repo root (the engine fingerprint hashes a repo-relative
# layout, so the image keeps it): docker build -t grid .
#
# The Maps key is baked into the page at build time; it is public by design
# (HTTP-referrer restricted on Google's side). Pass it as a build arg.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
ARG VITE_GOOGLE_MAPS_API_KEY=
ENV VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY
RUN npm run build

FROM python:3.13-slim AS api
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first, so a code change does not reinstall them. The `index`
# dependency group (imagery, audio) is for the offline indexers, not the API.
# `provenance` (c2pa-python, a manylinux wheel) signs the share card's C2PA
# manifest; it stays idle until a certificate and key arrive from Key Vault.
WORKDIR /app/services/api
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --group provenance --no-install-project

# The repo subset the API reads, at the same relative paths as in the repo.
COPY services/api/app ./app
COPY schema /app/schema
COPY data/equivalences.json /app/data/
COPY data/regions /app/data/regions
COPY fixtures /app/fixtures
COPY eval/addresses.json eval/resolved.json /app/eval/
COPY --from=web /web/dist /app/web/dist

# Briefs and downloaded datasets go to a mounted share in production
# (GRID_DATA_DIR, GRID_GROUND_DIR); locally they land under /app/data.
RUN useradd --system --uid 10001 --no-create-home grid \
    && mkdir -p /app/data/briefs /app/data/ground /mnt/grid \
    && chown -R grid:grid /app/data /mnt/grid
USER grid

ENV PATH="/app/services/api/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
