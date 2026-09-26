from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://gridmerge:gridmerge@localhost:5432/gridmerge"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Chunks of one document sent to Gemini at once, and retries on 429 / 5xx.
    extraction_concurrency: int = 3
    gemini_max_attempts: int = 6
    # Requests per minute across the whole app; the free tier allows 5 per model.
    # Raise it (or 0 = unpaced) on a paid key.
    gemini_rpm: int = 5
    geocoder: str = "nominatim"  # nominatim | none
    geocoder_user_agent: str = "GridMerge/0.1 (hackathon demo)"
    cors_origins: str = "http://localhost:5173"
    # gzip JSON responses (the pair list runs to megabytes). The deploy stack turns this
    # off because Caddy already compresses, with zstd where the browser takes it.
    compress_responses: bool = True

    # HIFLD transmission-line reference layer (existing lines). The snapshot committed
    # under app/data is loaded into an empty table at startup; refresh it with
    # `python -m scripts.load_hifld --fetch`.
    hifld_lines_url: str = (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
        "Electric_Power_Transmission_Lines/FeatureServer/0"
    )
    hifld_bbox: str = "-86.0,29.8,-80.8,31.6"  # FL–GA border region, minLng,minLat,maxLng,maxLat
    autoload_lines: bool = True
    # EIA-860M + SERTP projects from the committed source_docs/extracted/ CSVs, inserted
    # at startup when their plan is missing or its CSV changed (scripts.load_public_sources).
    autoload_public_sources: bool = True

    # Matching defaults (Req 6.5, 6.6, 7.2)
    default_radius_miles: float = 25.0

    # Ingestion limits (Req 1.4, 1.5)
    max_upload_bytes: int = 50 * 1024 * 1024
    max_utilities: int = 50

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
