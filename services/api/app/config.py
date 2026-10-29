"""Settings. Every variable carries the GRID_ prefix so ambient machine-wide
vars (another project's OPENAI_BASE_URL, say) can never override this app's
config. The full list with comments is services/api/.env.example."""

from functools import lru_cache
from pathlib import Path

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
    perception_dir: str = "data/perception"
    hearings_dir: str = "data/hearings"

    # Meta Model API, direct: used only by the offline indexers (app.perception,
    # app.hearings), never on the request path. Key from dev.meta.ai.
    meta_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    sam_model: str = "sam-3.1"
    transcribe_model: str = "muse-voice-transcribe-1.0"

    data_dir: str = "data/briefs"
    cors_origins: str = "http://localhost:5173,http://localhost:5180"
    # Country gate for brief routes. Empty = off. Only meaningful behind an edge that
    # sets the header from the client IP (Cloudflare: cf-ipcountry, Front Door: x-azure-
    # clientip-country); the app trusts the header, so never enable it without one.
    allowed_countries: str = ""
    country_header: str = "cf-ipcountry"

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
    def ground_path(self) -> Path:
        p = Path(self.ground_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def perception_path(self) -> Path:
        p = Path(self.perception_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def hearings_path(self) -> Path:
        p = Path(self.hearings_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def web_dist_path(self) -> Path:
        p = Path(self.web_dist)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def gate_on(self) -> bool:
        return self.auth_provider != "off"


@lru_cache
def get_settings() -> Settings:
    return Settings()
