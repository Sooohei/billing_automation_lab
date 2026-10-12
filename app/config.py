from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数（ローカルでは .env）から読む設定値。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    app_origin: str
    auth_mode: Literal["dev", "iap"] = "dev"
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_dir: Path = Path(".local/storage")
    gcs_bucket: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
