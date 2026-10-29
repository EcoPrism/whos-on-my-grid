"""Settings. Every variable carries the GRID_ prefix so ambient machine-wide
vars (another project's OPENAI_BASE_URL, say) can never override this app's
config. The full list with comments is services/api/.env.example."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/api/app/config.py -> repo root. The schema and fixtures live there.
REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]

# What the brief records as the model id. The gateway alias is a routing detail.
DRAFT_MODEL_ID = "muse-spark-1.3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(API_ROOT / ".env"), env_prefix="GRID_", extra="ignore"
    )

    # fixtures | agent | full
    brief_source: str = "fixtures"
    # openai | fake
    llm_provider: str = "fake"

    # Drafting via the Betahub LLM Gateway (LiteLLM proxy): virtual key + alias.
    openai_api_key: str = ""
    openai_base_url: str = (
        "https://llmgw-app.politehill-63ad311b.westeurope.azurecontainerapps.io/v1"
    )
    draft_model: str = "meta-flagship"

    # Verifying directly on Baseten.
    baseten_api_key: str = ""
    baseten_base_url: str = "https://inference.baseten.co/v1"
    verify_model: str = "meta-models/muse-spark-open"
    verify_strict_json: bool = True

    llm_max_tokens: int = 12000
    llm_timeout_seconds: float = 180.0
    verify_max_tokens: int = 4096
    verify_timeout_seconds: float = 60.0
    verify_concurrency: int = 8
    fetch_timeout_seconds: float = 10.0
    geocode_timeout_seconds: float = 15.0

    # Ground truth (full mode): facility database, service territory, prices.
    overpass_endpoints: str = (
        "https://overpass.openstreetmap.fr/api/interpreter,"
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter"
    )
    hifld_url: str = (
        "https://eedgis.pnnl.gov/arcgis/rest/services/Hosted/"
        "Electric_Service_Territories/FeatureServer/0/query"
    )
    ground_timeout_seconds: float = 30.0
    # Downloaded datasets (PeeringDB snapshot, EIA workbooks). Shared by every brief
    # cache directory, so an eval run with its own GRID_DATA_DIR does not re-download.
    ground_dir: str = "data/ground"
    # Step 4 indexes: what SAM 3.1 measured per area and what Voice Transcribe heard per
    # meeting. Committed data products; the API reads them, the indexers write them.
    # US only: other regions read theirs from data/regions/<id>/.
    perception_dir: str = "data/regions/us/perception"
    hearings_dir: str = "data/regions/us/hearings"

    # Meta Model API, direct: used only by the offline indexers (app.perception,
    # app.hearings), never on the request path. Key from dev.meta.ai.
    meta_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    sam_model: str = "sam-3.1"
    transcribe_model: str = "muse-voice-transcribe-1.0"

    data_dir: str = "data/briefs"
    # What-if scenarios (app/scenario): one JSON per scenario id, like the briefs. No
    # model call makes one, so they are ungated; the soft cap below is the belt.
    scenarios_dir: str = "data/scenarios"
    scenario_global_day: int = 2000
    # Census ACS (households per ZCTA for the what-if). Optional: api.census.gov needs
    # a key, and without one (or when that call fails) app/ground/census.py reads the
    # same table from data.census.gov's keyless table API.
    census_api_key: str = ""
    # Rendered share cards (app/card), one PNG per brief and engine. A cache: on Azure
    # it sits on the /mnt/grid share beside the briefs.
    cards_dir: str = "data/cards"
    # Where the site is served, for absolute links in Open Graph tags, the share text
    # and the card's disclosure line. Empty = the request's own origin (local runs).
    public_base_url: str = ""
    # C2PA content credentials on the card: a PEM certificate chain (end-entity first),
    # given inline (GRID_C2PA_CERT_PEM, how Azure passes it from Key Vault) or as a file
    # (GRID_C2PA_CERT_PATH), and its PEM private key. Blank = off; the card still carries
    # XMP and the disclosure band. The key is a SecretStr so no repr or log prints it.
    # An empty timestamp URL signs without a timestamp (tests, offline runs).
    c2pa_cert_pem: str = ""
    c2pa_cert_path: str = ""
    c2pa_private_key: SecretStr = SecretStr("")
    c2pa_timestamp_url: str = "http://timestamp.digicert.com"
    cors_origins: str = "http://localhost:5173,http://localhost:5180"
    # Country gate for brief routes. Empty = off. Only meaningful behind an edge that
    # sets the header from the client IP (Cloudflare: cf-ipcountry, Front Door: x-azure-
    # clientip-country); the app trusts the header, so never enable it without one.
    allowed_countries: str = ""
    country_header: str = "cf-ipcountry"
    # Regions this process serves (app/regions), comma-separated ids: "us,ie" enables
    # Ireland on the same image. A request names its region, or the country header
    # picks one (only when the gate above is on), or it gets the default.
    regions: str = "us"
    default_region: str = "us"

    # Sign-in gate for *new* briefs. off = anyone can generate (local dev); google =
    # Google Identity Services id_tokens; fake = "fake:<sub>:<email>" tokens (tests only).
    # Viewing a brief, and running a test-set address, never needs sign-in.
    auth_provider: str = "off"
    google_client_id: str = ""
    # HS256 secret for the session cookie. Required when auth_provider is not off.
    session_secret: str = ""
    cookie_secure: bool = True
    session_days: int = 30
    # Where sign-ins and generated briefs are recorded: memory | table (Azure Table
    # Storage, reached with the managed identity). Rows hold email and brief id, never
    # an address.
    usage_store: str = "memory"
    storage_account: str = ""
    quota_per_user_day: int = 5
    quota_global_day: int = 40
    # The built web app, served by this process when the directory exists.
    web_dist: str = "web/dist"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def scenarios_path(self) -> Path:
        p = Path(self.scenarios_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def cards_path(self) -> Path:
        p = Path(self.cards_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def ground_path(self) -> Path:
        p = Path(self.ground_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def perception_path(self) -> Path:
        return _repo_path(self.perception_dir)

    @property
    def hearings_path(self) -> Path:
        return _repo_path(self.hearings_dir)

    @property
    def web_dist_path(self) -> Path:
        p = Path(self.web_dist)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def gate_on(self) -> bool:
        return self.auth_provider != "off"

    @property
    def region_ids(self) -> tuple[str, ...]:
        """GRID_REGIONS as ids, lowercased, blanks and repeats dropped, in order."""
        ids = (r.strip().lower() for r in self.regions.split(","))
        return tuple(dict.fromkeys(r for r in ids if r))

    @property
    def default_region_id(self) -> str:
        return self.default_region.strip().lower()


# Where the step-4 indexes lived before data/regions/. A .env copied from an older
# .env.example still names them; read as the new place, not as an empty index.
_LEGACY_DIRS = {
    "data/perception": "data/regions/us/perception",
    "data/hearings": "data/regions/us/hearings",
}


def _repo_path(value: str) -> Path:
    value = _LEGACY_DIRS.get(value.replace("\\", "/").rstrip("/"), value)
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
