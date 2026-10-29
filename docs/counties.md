# Hearing coverage

Bodies whose official meeting archive is indexed for the "Hearing" section. The source of truth
is `data/regions/us/hearings/sources.json`; one transcript file per indexed meeting sits beside
it under `data/regions/us/hearings/<body>/`. Recordings are fetched from the official archive only, never from video
platforms. Addresses in a county with no indexed body get a `gap` saying so, and the section stays
the model's recollection (`reported`), never `measured`.

| County / body | State | Archive | Indexed meetings | Status |
|---|---|---|---|---|
| Prince William County Board of County Supervisors | VA | Granicus (`pwcgov.granicus.com`, view 23) | 12–13 Dec 2023, clip 3410 (Digital Gateway rezonings: opening, motions and vote; no captions, audio needed); 14 Apr 2026, clip 3817 (public comment and the resolution not to appeal; captions) | indexed from captions; Voice Transcribe pass pending audio |
| Loudoun County Board of Supervisors | VA | Granicus (`loudoun.granicus.com`, view 90) | 18 Mar 2025, clip 7909 (Public Input Session II; item 7, Data Center Standards and Locations Phase 1; captions) | indexed from captions; Voice Transcribe pass pending audio |
| Pima County Board of Supervisors | AZ | Legistar agendas, Granicus video (`pima.granicus.com`, view 3) | 16 Dec 2025, clip 1873 (item 6, Binding Memorandum of Agreement, Houghton Data Center Project / Project Blue; captions). The 17 Jun 2025 land-sale vote is missing from the archive (404) | indexed from captions; Voice Transcribe pass pending audio |
| Tucson Mayor and Council | AZ | OnBase Agenda Online (written record only; video is on a video platform, which we do not use) | Decision on record: 6 Aug 2025 Legal Action Report, Project Blue development agreement rejected | decision only |
| Kenosha County Board | WI | CivicPlus agendas; video on a video platform only | — | planned |
| Maricopa County Board of Supervisors | AZ | OnBase Agenda Online; video on a video platform only | — | planned |

## What "indexed" means

- Each meeting has one or more **windows** (seconds into the recording, taken from the archive's
  own agenda index points). Only the windows are transcribed; the section's `gap` says which.
- **Turns** are verbatim. With audio, Muse Voice Transcribe (`muse-voice-transcribe-1.0`,
  diarization mode) produces them and the archive's closed captions, where present, are kept as
  a cross-check (`agreement`, token F1). Without audio, `--captions-only` builds turns from the
  archive's captions; the section then carries `model: null` because no model of ours produced
  the words.
- **Speaker roles** (chair, supervisor, staff, applicant, resident) are the one inferred field:
  Muse Spark reads each stretch of transcript and labels the speakers, with its confidence.
- **Decisions** are hand-entered records of a vote on a named campus (rejected, approved), each
  with the official page that says so. They appear in "Coming" as `rejected` or `announced`
  entries within fifteen miles, with the vote as a claim the verifier checks.

## Adding a body

1. Add it to `data/regions/us/hearings/sources.json` with its archive, counties and a meeting
   with windows.
2. Download the recording from the archive page into
   `data/regions/us/hearings/audio/<site>_<clip>.mp3`
   (or pass `--download`), then `uv run python -m app.hearings.index --meeting <id>`.
   With captions only: `--captions-only`.
3. Commit the transcript file. The brief picks it up on the next request.
