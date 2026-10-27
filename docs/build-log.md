# Build log

Dated entries of what was built, with which tools. Judges can use this to tell event work apart
from anything pre-existing.

## 2026-10-27
- Repository created. README (vision), `schema/brief.schema.json` (the contract), five fixture
  briefs with fictional operators, coverage and build-log docs. No code wired to real data.
- Web app (`web/`, Vite + React + TypeScript + Tailwind + Leaflet) running on the fixtures:
  address box, brief page (five sections with status rail, five-mile map, claims appendix with
  verifier verdicts), share card. `BRIEF_SOURCE=fixtures` is the only mode so far.
