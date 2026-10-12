import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.extraction.models import ExtractionResult
from app.invoices.models import Invoice
from app.partners.models import Partner
from app.payment_requests.models import PaymentRequestInput, PaymentRequestStatus

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class InvoiceFilters:
    """一覧の絞り込み条件。None は指定なし。"""

    received_from: date | None = None
    received_to: date | None = None
    partner_id: uuid.UUID | None = None
    status: PaymentRequestStatus | None = None


@dataclass(frozen=True)
class InvoiceRow:
    """一覧の 1 行。支払い依頼インプットがあればその値、なければ抽出結果の値。"""

    invoice_id: uuid.UUID
    received_at: datetime
    partner_name: str | None
    amount_including_tax: int | None
    due_date: date | None
    status: PaymentRequestStatus


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

    def search(self, filters: InvoiceFilters, offset: int, limit: int) -> list[InvoiceRow]:
        """請求書データを起点に、抽出結果と支払い依頼インプットを外部結合して一覧の行を返す。

        支払期日の古い順（空は末尾）、同じなら受信日時の古い順、それも同じなら請求書 ID の順。
        """
        has_input = PaymentRequestInput.invoice_id.is_not(None)

        def input_or_extraction(input_column: Any, extraction_column: Any) -> Any:
            # インプットがあれば、その項目が空でも抽出結果で埋めない
            return case((has_input, input_column), else_=extraction_column)

        partner_id = input_or_extraction(
            PaymentRequestInput.partner_id, ExtractionResult.partner_id
        )
        amount = input_or_extraction(
            PaymentRequestInput.amount_including_tax, ExtractionResult.amount_including_tax
        )
        due_date = input_or_extraction(PaymentRequestInput.due_date, ExtractionResult.due_date)
        status = func.coalesce(PaymentRequestInput.status, PaymentRequestStatus.UNSUBMITTED.value)

        statement = (
            select(Invoice.id, Invoice.received_at, Partner.name, amount, due_date, status)
            .outerjoin(ExtractionResult, ExtractionResult.invoice_id == Invoice.id)
            .outerjoin(PaymentRequestInput, PaymentRequestInput.invoice_id == Invoice.id)
            # 削除済みの取引先も、取引先名を表示する
            .outerjoin(Partner, Partner.id == partner_id)
        )
        if filters.received_from is not None:
            statement = statement.where(Invoice.received_at >= _jst_midnight(filters.received_from))
        if filters.received_to is not None:
            next_day = filters.received_to + timedelta(days=1)
            statement = statement.where(Invoice.received_at < _jst_midnight(next_day))
        if filters.partner_id is not None:
            statement = statement.where(partner_id == filters.partner_id)
        if filters.status is not None:
            statement = statement.where(status == filters.status.value)

        statement = (
            statement.order_by(due_date.asc().nulls_last(), Invoice.received_at, Invoice.id)
            .offset(offset)
            .limit(limit)
        )
        return [
            InvoiceRow(
                invoice_id=row[0],
                received_at=row[1],
                partner_name=row[2],
                amount_including_tax=row[3],
                due_date=row[4],
                status=PaymentRequestStatus(row[5]),
            )
            for row in self._session.execute(statement)
        ]


def _jst_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=JST)
