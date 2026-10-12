import contextlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.orm import Session

from app.extraction.extractor import RawExtraction
from app.extraction.models import ExtractionResult
from app.gmail.client import GmailAuthError
from app.invoices.models import Invoice
from app.jobs.hourly import ADVISORY_LOCK_KEY, run_hourly
from app.storage.local import LocalFileStorage
from tests.fakes import FakeGmailClient, FakeInvoiceExtractor
from tests.test_ingest import NOW, START_DATE, make_message
from tests.test_invoice_repository import make_invoice
from tests.test_partner_repository import add_partner


@pytest.fixture(autouse=True)
def partner(session: Session) -> None:
    add_partner(session, "Aメディア", ["billing@a-media.jp"])
    session.commit()


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path)


@pytest.fixture
def other_connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        yield connection
        connection.scalar(select(func.pg_advisory_unlock_all()))
        connection.commit()


def try_lock(connection: Connection) -> bool:
    return bool(connection.scalar(select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY))))


def invoice_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Invoice)) or 0


def test_取込を行いエラーがなければ成功を返す(
    engine: Engine, session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message()])

    assert run_hourly(engine, gmail, FakeInvoiceExtractor(), storage, START_DATE, NOW) is True
    assert invoice_count(session) == 1


def test_取込でエラーがあれば失敗を返す(engine: Engine, storage: LocalFileStorage) -> None:
    gmail = FakeGmailClient([make_message()])
    gmail.errors["msg-1"] = RuntimeError("取得できない")

    assert run_hourly(engine, gmail, FakeInvoiceExtractor(), storage, START_DATE, NOW) is False


def test_取込で想定外のエラーが起きても失敗を返して終わる(
    engine: Engine, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_ingest(*args: object) -> None:
        raise RuntimeError("DB に接続できない")

    monkeypatch.setattr("app.jobs.hourly.ingest", broken_ingest)

    assert (
        run_hourly(engine, FakeGmailClient([]), FakeInvoiceExtractor(), storage, START_DATE, NOW)
        is False
    )


def test_ロックを取れなければ何もせずに終わる(
    engine: Engine,
    session: Session,
    storage: LocalFileStorage,
    other_connection: Connection,
) -> None:
    assert try_lock(other_connection)
    gmail = FakeGmailClient([make_message()])

    assert run_hourly(engine, gmail, FakeInvoiceExtractor(), storage, START_DATE, NOW) is True
    assert gmail.fetched_ids == []
    assert invoice_count(session) == 0


@pytest.mark.parametrize("fails", [False, True], ids=["成功", "想定外のエラー"])
def test_終わったらロックを外す(
    engine: Engine,
    storage: LocalFileStorage,
    other_connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    if fails:
        monkeypatch.setattr("app.jobs.hourly._run_steps", lambda *args: 1 / 0)

    with contextlib.suppress(ZeroDivisionError):
        run_hourly(engine, FakeGmailClient([]), FakeInvoiceExtractor(), storage, START_DATE, NOW)

    assert try_lock(other_connection)


def test_運用開始日と実行日時を取込に渡す(
    engine: Engine, session: Session, storage: LocalFileStorage
) -> None:
    # 実行日時の 60 日前の日（10/11）より前に受信したメールは取り込まない
    gmail = FakeGmailClient([make_message(received_at=datetime(2026, 10, 5, tzinfo=UTC))])
    now = datetime(2026, 12, 10, 3, 0, tzinfo=UTC)

    run_hourly(engine, gmail, FakeInvoiceExtractor(), storage, date(2026, 10, 1), now)

    assert invoice_count(session) == 0


def extraction_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ExtractionResult)) or 0


def test_取込のあとに抽出を行う(
    engine: Engine, session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message()])
    extractor = FakeInvoiceExtractor({b"%PDF-A": RawExtraction(invoice_number="INV-1")})

    assert run_hourly(engine, gmail, extractor, storage, START_DATE, NOW) is True

    [result] = session.scalars(select(ExtractionResult)).all()
    assert result.invoice_number == "INV-1"


def test_取込全体が止まっても抽出を行い失敗を返す(
    engine: Engine, session: Session, storage: LocalFileStorage
) -> None:
    # 前回までに取り込み、まだ抽出していない請求書データ
    invoice = make_invoice("a" * 64)
    storage.save(invoice.file_key, b"%PDF-A")
    session.add(invoice)
    session.commit()
    gmail = FakeGmailClient([])
    gmail.list_error = GmailAuthError("invalid_grant")

    assert run_hourly(engine, gmail, FakeInvoiceExtractor(), storage, START_DATE, NOW) is False
    assert extraction_count(session) == 1


def test_抽出でエラーがあれば失敗を返す(
    engine: Engine, session: Session, storage: LocalFileStorage
) -> None:
    gmail = FakeGmailClient([make_message()])
    extractor = FakeInvoiceExtractor()
    extractor.errors[b"%PDF-A"] = RuntimeError("読み取れない")

    assert run_hourly(engine, gmail, extractor, storage, START_DATE, NOW) is False
    assert invoice_count(session) == 1
    assert extraction_count(session) == 0
