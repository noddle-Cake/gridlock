from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://gridmerge:gridmerge@localhost:5432/gridmerge"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    geocoder: str = "nominatim"  # nominatim | none
    geocoder_user_agent: str = "GridMerge/0.1 (hackathon demo)"
    cors_origins: str = "http://localhost:5173"

    # Matching defaults (Req 6.5, 6.6, 7.2)
    default_radius_miles: float = 25.0
    default_pad_days: int = 30
    max_overlap_days: int = 365

    # Ingestion limits (Req 1.4, 1.5)
    max_upload_bytes: int = 50 * 1024 * 1024
    max_utilities: int = 50

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
