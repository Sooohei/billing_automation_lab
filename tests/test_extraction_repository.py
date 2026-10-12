from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.extraction.models import ExtractionResult
from app.extraction.repository import ExtractionRepository
from app.invoices.models import Invoice
from tests.test_invoice_repository import make_invoice
from tests.test_partner_repository import add_partner


def add_invoice(session: Session, sha256_char: str, received_day: int) -> Invoice:
    invoice = make_invoice(sha256_char * 64)
    invoice.received_at = datetime(2026, 10, received_day, tzinfo=UTC)
    session.add(invoice)
    session.flush()
    return invoice


def test_抽出結果がない請求書データを受信日時の古い順に返す(session: Session) -> None:
    newer = add_invoice(session, "a", 10)
    older = add_invoice(session, "b", 5)
    extracted = add_invoice(session, "c", 1)
    repository = ExtractionRepository(session)
    repository.add(ExtractionResult(invoice_id=extracted.id))
    session.flush()

    assert repository.list_invoices_without_result() == [older, newer]


def test_抽出結果を保存して読み出せる(session: Session) -> None:
    invoice = add_invoice(session, "a", 5)
    partner = add_partner(session, "Aメディア", ["billing@a-media.jp"])
    repository = ExtractionRepository(session)

    repository.add(
        ExtractionResult(
            invoice_id=invoice.id,
            partner_id=partner.id,
            invoice_number="AM-2026-10-001",
            qualified_invoice_issuer_number="T1234567890123",
            issue_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31),
            amount_excluding_tax=1_000_000,
            tax_amount=100_000,
            amount_including_tax=1_100_000,
        )
    )
    session.flush()
    session.expire_all()

    result = repository.get(invoice.id)
    assert result is not None
    assert result.partner_id == partner.id
    assert result.due_date == date(2026, 10, 31)
    assert result.amount_including_tax == 1_100_000
    assert result.extracted_at is not None


def test_取引先と抽出項目は空でも保存できる(session: Session) -> None:
    invoice = add_invoice(session, "a", 5)
    repository = ExtractionRepository(session)

    repository.add(ExtractionResult(invoice_id=invoice.id))
    session.flush()

    result = repository.get(invoice.id)
    assert result is not None
    assert result.partner_id is None
    assert result.invoice_number is None


def test_1件の請求書データに抽出結果は1件しか作れない(session: Session) -> None:
    invoice = add_invoice(session, "a", 5)
    session.add(ExtractionResult(invoice_id=invoice.id))
    session.flush()
    session.expunge_all()

    session.add(ExtractionResult(invoice_id=invoice.id))
    with pytest.raises(IntegrityError, match="pk_extraction_results"):
        session.flush()
