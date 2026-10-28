"""Perception indexer: two vintages of USDA NAIP aerial imagery in, the
large roofs that appeared between them out (`data/perception/<area>.json`),
read per brief by `app.ground.imagery`. Run offline:

    uv run python -m app.perception.index --area new_albany

Imagery is public domain and keyless (Microsoft Planetary Computer for the
earlier vintage, USDA FPAC's imagery service for the latest). Segmentation is
SAM 3.1 on the Meta Model API (GRID_META_API_KEY)."""
