from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""  # empty allowed in SAMPLE_MODE
    cors_origins: str  # required — no default; startup fails if not set
    sample_mode: bool = False
    sample_data_dir: str = "data/sample"
    vite_api_base_url: str = ""  # frontend only, backend reads for validation


settings = Settings()
