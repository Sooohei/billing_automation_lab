import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.extract import extract
from app.extraction.extractor import InvoiceExtractor, RawExtraction
from app.extraction.models import ExtractionResult
from app.gmail.client import GmailClient
from app.invoices.ingest import ingest
from app.invoices.models import Invoice
from app.partners.models import Partner
from app.storage.local import LocalFileStorage
from tests.fakes import FakeInvoiceExtractor
from tests.test_partner_repository import add_partner

FULL = RawExtraction(
    invoice_number="AM-2026-10-001",
    qualified_invoice_issuer_number="T1234-5678-90123",
    issue_date="2026-10-01",
    due_date="2026-10-31",
    amount_excluding_tax="1,000,000",
    tax_amount="100,000",
    amount_including_tax="1,100,000",
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path)


@pytest.fixture
def partner(session: Session) -> Partner:
    return add_partner(session, "Aメディア", ["billing@a-media.jp"])


def add_invoice(
    session: Session,
    storage: LocalFileStorage,
    pdf: bytes,
    *,
    sender_email: str = "billing@a-media.jp",
    received_day: int = 5,
) -> Invoice:
    key = f"invoices/{pdf.hex()}.pdf"
    storage.save(key, pdf)
    invoice = Invoice(
        file_key=key,
        file_sha256=pdf.hex(),
        file_name="請求書.pdf",
        sender_email=sender_email,
        subject="10月分のご請求",
        received_at=datetime(2026, 10, received_day, tzinfo=UTC),
        gmail_message_id=f"msg-{pdf.hex()}",
    )
    session.add(invoice)
    session.commit()
    return invoice


def result_of(session: Session, invoice_id: uuid.UUID) -> ExtractionResult | None:
    session.expire_all()
    return session.get(ExtractionResult, invoice_id)


def test_読み取った値を形式チェックして保存する(
    session: Session, storage: LocalFileStorage, partner: Partner
) -> None:
    invoice = add_invoice(session, storage, b"%PDF-A")

    result = extract(session, FakeInvoiceExtractor({b"%PDF-A": FULL}), storage)

    assert (result.created_count, result.has_errors) == (1, False)
    saved = result_of(session, invoice.id)
    assert saved is not None
    assert saved.partner_id == partner.id
    assert saved.invoice_number == "AM-2026-10-001"
    assert saved.qualified_invoice_issuer_number == "T1234567890123"
    assert (saved.issue_date, saved.due_date) == (date(2026, 10, 1), date(2026, 10, 31))
    assert saved.amount_excluding_tax == 1_000_000
    assert saved.tax_amount == 100_000
    assert saved.amount_including_tax == 1_100_000
    assert saved.extracted_at is not None


def test_読み取れなかった項目と形式チェックに通らない項目は空にする(
    session: Session, storage: LocalFileStorage, partner: Partner
) -> None:
    invoice = add_invoice(session, storage, b"%PDF-A")
    raw = RawExtraction(invoice_number="INV-1", due_date="2026-02-30", tax_amount="0")

    extract(session, FakeInvoiceExtractor({b"%PDF-A": raw}), storage)

    saved = result_of(session, invoice.id)
    assert saved is not None
    assert saved.invoice_number == "INV-1"
    assert saved.due_date is None
    # 0 円は「読み取り済」
    assert saved.tax_amount == 0
    assert saved.amount_including_tax is None


def test_対応する取引先がなければ取引先を空にして抽出結果を作る(
    session: Session, storage: LocalFileStorage, partner: Partner
) -> None:
    invoice = add_invoice(session, storage, b"%PDF-A", sender_email="unknown@example.com")

    extract(session, FakeInvoiceExtractor({b"%PDF-A": FULL}), storage)

    saved = result_of(session, invoice.id)
    assert saved is not None
    assert saved.partner_id is None
    assert saved.invoice_number == "AM-2026-10-001"


def test_抽出結果がある請求書データは処理せず上書きしない(
    session: Session, storage: LocalFileStorage, partner: Partner
) -> None:
    invoice = add_invoice(session, storage, b"%PDF-A")
    extract(session, FakeInvoiceExtractor({b"%PDF-A": FULL}), storage)

    result = extract(
        session, FakeInvoiceExtractor({b"%PDF-A": RawExtraction(invoice_number="X")}), storage
    )

    assert result.created_count == 0
    saved = result_of(session, invoice.id)
    assert saved is not None
    assert saved.invoice_number == "AM-2026-10-001"


def test_エラーになった請求書データは抽出結果を作らず次回抽出する(
    session: Session, storage: LocalFileStorage, partner: Partner, caplog: pytest.LogCaptureFixture
) -> None:
    failing = add_invoice(session, storage, b"%PDF-A", received_day=1)
    other = add_invoice(session, storage, b"%PDF-B", received_day=2)
    extractor = FakeInvoiceExtractor({b"%PDF-A": FULL})
    extractor.errors[b"%PDF-A"] = RuntimeError("読み取れない")

    result = extract(session, extractor, storage)

    # エラーになっても、他の請求書データの処理は続ける
    assert result.failed_invoice_ids == [failing.id]
    assert result.created_count == 1
    assert result_of(session, failing.id) is None
    assert result_of(session, other.id) is not None
    assert f"invoice_id={failing.id}" in caplog.text

    assert extract(session, extractor, storage).created_count == 1
    assert result_of(session, failing.id) is not None


def test_請求書ファイルを読み出せなければエラーにする(
    session: Session, tmp_path: Path, partner: Partner
) -> None:
    add_invoice(session, LocalFileStorage(tmp_path / "saved"), b"%PDF-A")

    result = extract(session, FakeInvoiceExtractor(), LocalFileStorage(tmp_path / "empty"))

    assert result.has_errors


def test_リポジトリのサンプルの読み取り結果を保存する(
    session: Session, storage: LocalFileStorage, partner: Partner
) -> None:
    add_partner(session, "Bネットワークス", ["invoice@b-networks.jp"])
    add_partner(session, "Cアド", ["info@c-ad.jp"])
    add_partner(session, "Dパブリッシング", ["billing@d-publishing.jp"])
    session.commit()
    ingest(session, GmailClient(), storage, date(2026, 10, 1), datetime(2026, 10, 12, tzinfo=UTC))

    result = extract(session, InvoiceExtractor(), storage)

    assert (result.created_count, result.has_errors) == (5, False)
    rows = session.execute(
        select(Invoice.file_name, ExtractionResult.amount_including_tax)
        .join(ExtractionResult, ExtractionResult.invoice_id == Invoice.id)
        .order_by(Invoice.file_name)
    ).all()
    assert [tuple(row) for row in rows] == [
        ("BN-1001.pdf", 550_000),
        ("BN-1002.pdf", None),
        ("DP_請求書_202610.pdf", None),
        ("INVOICE_202610.PDF", 330_000),
        ("請求書_AM-2026-10-001.pdf", 1_100_000),
    ]
