"""Scenario cache: one JSON file per scenario id under data/scenarios, stamped
with the same engine fingerprint as briefs. The id is a hash of the inputs;
the ZIP appears only inside the scenario itself."""

from app.brief.cache import BriefCache


class ScenarioCache(BriefCache):
    id_field = "scenario_id"
    kind = "scenario"
