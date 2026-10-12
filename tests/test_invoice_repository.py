from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.invoices.models import Invoice
from app.invoices.repository import InvoiceRepository


def make_invoice(sha256: str, message_id: str = "msg-1") -> Invoice:
    return Invoice(
        file_key=f"invoices/{sha256}.pdf",
        file_sha256=sha256,
        file_name="請求書.pdf",
        sender_email="billing@a-media.jp",
        subject="10月分のご請求",
        received_at=datetime(2026, 10, 5, 1, 0, tzinfo=UTC),
        gmail_message_id=message_id,
    )


def test_請求書データを追加すると取込日時が入る(session: Session) -> None:
    invoice = make_invoice("a" * 64)

    InvoiceRepository(session).add_invoice(invoice)
    session.flush()
    session.refresh(invoice)

    assert invoice.id is not None
    assert invoice.ingested_at is not None


def test_取込済みのメールのIDだけを返す(session: Session) -> None:
    repository = InvoiceRepository(session)
    repository.add_ingested_message("msg-1")
    repository.add_ingested_message("msg-2")
    session.flush()

    assert repository.find_ingested_message_ids(["msg-1", "msg-3"]) == {"msg-1"}
    assert repository.find_ingested_message_ids([]) == set()


def test_請求書データがあるSHA256だけを返す(session: Session) -> None:
    repository = InvoiceRepository(session)
    repository.add_invoice(make_invoice("a" * 64))
    session.flush()

    assert repository.find_existing_sha256s(["a" * 64, "b" * 64]) == {"a" * 64}
    assert repository.find_existing_sha256s([]) == set()


def test_同じSHA256の請求書データは追加できない(session: Session) -> None:
    repository = InvoiceRepository(session)
    repository.add_invoice(make_invoice("a" * 64, "msg-1"))
    session.flush()

    repository.add_invoice(make_invoice("a" * 64, "msg-2"))
    with pytest.raises(IntegrityError, match="uq_invoices_file_sha256"):
        session.flush()
