from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_session
from app.main import create_app


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """テスト用の DB（TEST_DATABASE_URL）に、テストの開始時にマイグレーションを適用する。"""
    url = get_settings().test_database_url
    if not url:
        pytest.exit("TEST_DATABASE_URL が設定されていません", returncode=1)

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """各テストの前に全テーブルを空にしてから、セッションを渡す。"""
    table_names = [table.name for table in Base.metadata.sorted_tables]
    if table_names:
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(table_names)} CASCADE"))

    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
