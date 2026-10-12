import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus


class PaymentRequestRepository:
    """支払い依頼インプットの読み書き。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_if_absent(self, invoice_id: uuid.UUID, **values: Any) -> None:
        """支払い依頼インプットがなければ作る。同時に呼ばれても 1 件しかできない。"""
        statement = (
            insert(PaymentRequestInput)
            .values(invoice_id=invoice_id, status=PaymentRequestStatus.UNSUBMITTED, **values)
            .on_conflict_do_nothing(index_elements=[PaymentRequestInput.invoice_id])
        )
        self._session.execute(statement)

    def get(self, invoice_id: uuid.UUID) -> PaymentRequestInput | None:
        return self._session.get(PaymentRequestInput, invoice_id)

    def get_for_update(self, invoice_id: uuid.UUID) -> PaymentRequestInput | None:
        """SELECT ... FOR UPDATE でロックして返す。"""
        statement = (
            select(PaymentRequestInput)
            .where(PaymentRequestInput.invoice_id == invoice_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.scalars(statement).one_or_none()
