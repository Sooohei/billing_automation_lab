"""1 時間ごとのバッチ。SR-01 の取込のあとに、SR-02 の抽出を行う。

uv run python -m app.jobs.hourly
"""

import logging
import sys
from datetime import UTC, date, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.gmail.client import GmailClient
from app.invoices.ingest import ingest
from app.storage.dependencies import create_file_storage
from app.storage.storage import FileStorage

logger = logging.getLogger(__name__)

# バッチが同時に動かないようにする advisory lock のキー（アプリ内で一意な値）
ADVISORY_LOCK_KEY = 20261001


def run_hourly(
    engine: Engine,
    gmail_client: GmailClient,
    storage: FileStorage,
    start_date: date,
    now: datetime,
) -> bool:
    """バッチを 1 回実行する。エラーがなければ True を返す。"""
    with engine.connect() as lock_connection:
        locked = lock_connection.scalar(select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY)))
        if not locked:
            logger.info("前回のバッチがまだ動いているため、何もせずに終わります")
            return True
        try:
            return _run_steps(engine, gmail_client, storage, start_date, now)
        finally:
            lock_connection.scalar(select(func.pg_advisory_unlock(ADVISORY_LOCK_KEY)))
            lock_connection.commit()


def _run_steps(
    engine: Engine,
    gmail_client: GmailClient,
    storage: FileStorage,
    start_date: date,
    now: datetime,
) -> bool:
    succeeded = True

    try:
        with Session(engine) as session:
            result = ingest(session, gmail_client, storage, start_date, now)
        succeeded = succeeded and not result.has_errors
    except Exception:
        # 取込全体が止まっても、続く SR-02 の抽出は行う
        logger.exception("取込で想定外のエラーが起きました")
        succeeded = False

    # SR-02 の抽出は、SR-02 の実装で追加する

    return succeeded


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    settings = get_settings()
    if settings.ingest_start_date is None:
        logger.error("INGEST_START_DATE が設定されていません")
        sys.exit(1)

    succeeded = run_hourly(
        get_engine(),
        GmailClient(),
        create_file_storage(settings),
        settings.ingest_start_date,
        datetime.now(UTC),
    )
    # エラーがあった場合は、ジョブを失敗として終わる
    sys.exit(0 if succeeded else 1)


if __name__ == "__main__":
    main()
