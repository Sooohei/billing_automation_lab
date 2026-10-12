from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数（ローカルでは .env）から読む設定値。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    # Web アプリのオリジン。カンマ区切りで複数を書ける（例: localhost と 127.0.0.1）
    app_origin: str
    auth_mode: Literal["dev", "iap"] = "dev"
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_dir: Path = Path(".local/storage")
    gcs_bucket: str | None = None
    # SR-01 の運用開始日（日本時間）。1 時間ごとのバッチで使う
    ingest_start_date: date | None = None

    @property
    def app_origins(self) -> set[str]:
        return {origin.strip() for origin in self.app_origin.split(",") if origin.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
