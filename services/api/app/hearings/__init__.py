"""Hearing indexer: official meeting recordings in, speaker-attributed
transcript windows out (`data/regions/us/hearings/<body>/<meeting>.json`), read per
brief
by `app.ground.hearings`. Run offline:

    uv run python -m app.hearings.index --meeting pwc-2023-12-12 \
        --audio data/regions/us/hearings/audio/pwcgov_3410.mp3

Audio goes through Muse Voice Transcribe (Meta Model API, GRID_META_API_KEY);
the archive's own closed captions, where it publishes them, are stored
alongside as a cross-check, or used on their own with `--captions-only`."""
