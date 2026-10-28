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

    data_dir: str = "data/briefs"
    cors_origins: str = "http://localhost:5173,http://localhost:5180"
    # Country gate for brief routes. Empty = off. Only meaningful behind an edge that
    # sets the header from the client IP (Cloudflare: cf-ipcountry, Front Door: x-azure-
    # clientip-country); the app trusts the header, so never enable it without one.
    allowed_countries: str = ""
    country_header: str = "cf-ipcountry"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def ground_path(self) -> Path:
        p = Path(self.ground_dir)
        return p if p.is_absolute() else REPO_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
