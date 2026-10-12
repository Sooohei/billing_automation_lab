from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.invoices.models import Invoice
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus
from app.payment_requests.repository import PaymentRequestRepository
from tests.test_invoice_repository import make_invoice


@pytest.fixture
def invoice(session: Session) -> Invoice:
    invoice = make_invoice("a" * 64)
    session.add(invoice)
    session.flush()
    return invoice


def test_支払い依頼インプットがなければ未申請で作る(session: Session, invoice: Invoice) -> None:
    repository = PaymentRequestRepository(session)

    repository.create_if_absent(
        invoice.id, created_from_extraction=True, title="202610_A_メディア費"
    )

    created = repository.get(invoice.id)
    assert created is not None
    assert created.status == PaymentRequestStatus.UNSUBMITTED
    assert not created.is_submitted
    assert created.title == "202610_A_メディア費"
    assert created.created_from_extraction is True
    assert created.created_at is not None


def test_支払い依頼インプットがあれば作り直さない(session: Session, invoice: Invoice) -> None:
    repository = PaymentRequestRepository(session)
    repository.create_if_absent(invoice.id, created_from_extraction=True, title="最初の値")

    repository.create_if_absent(invoice.id, created_from_extraction=False, title="2 回目の値")

    created = repository.get(invoice.id)
    assert created is not None
    assert created.title == "最初の値"
    assert created.created_from_extraction is True


def test_ロックして読み出せる(session: Session, invoice: Invoice) -> None:
    repository = PaymentRequestRepository(session)
    repository.create_if_absent(invoice.id, created_from_extraction=False)

    locked = repository.get_for_update(invoice.id)

    assert locked is not None
    assert locked.invoice_id == invoice.id


def submitted(invoice: Invoice, **overrides: object) -> PaymentRequestInput:
    values: dict[str, object] = {
        "invoice_id": invoice.id,
        "created_from_extraction": False,
        "status": PaymentRequestStatus.SUBMITTED,
        "freee_payment_request_id": 9001,
        "applicant_email": "dev@example.com",
        "applied_at": datetime(2026, 10, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return PaymentRequestInput(**values)


def test_申請済で識別子と申請者と申請日時があれば保存できる(
    session: Session, invoice: Invoice
) -> None:
    session.add(submitted(invoice))
    session.flush()


@pytest.mark.parametrize("field", ["freee_payment_request_id", "applicant_email", "applied_at"])
def test_申請済で識別子か申請者か申請日時が空なら保存できない(
    session: Session, invoice: Invoice, field: str
) -> None:
    session.add(submitted(invoice, **{field: None}))

    with pytest.raises(IntegrityError, match="ck_payment_request_inputs_submitted_fields"):
        session.flush()


def test_申請状態は未申請か申請済だけ(session: Session, invoice: Invoice) -> None:
    session.add(
        PaymentRequestInput(invoice_id=invoice.id, created_from_extraction=False, status="x")
    )

    with pytest.raises(IntegrityError, match="ck_payment_request_inputs_status"):
        session.flush()
