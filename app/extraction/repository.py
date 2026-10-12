import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.models import ExtractionResult
from app.invoices.models import Invoice


class ExtractionRepository:
    """抽出結果の読み書き。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_invoices_without_result(self) -> list[Invoice]:
        """抽出結果がない請求書データを、受信日時の古い順に返す。"""
        statement = (
            select(Invoice)
            .outerjoin(ExtractionResult, ExtractionResult.invoice_id == Invoice.id)
            .where(ExtractionResult.invoice_id.is_(None))
            .order_by(Invoice.received_at, Invoice.id)
        )
        return list(self._session.scalars(statement))

    def get(self, invoice_id: uuid.UUID) -> ExtractionResult | None:
        return self._session.get(ExtractionResult, invoice_id)

    def add(self, result: ExtractionResult) -> None:
        self._session.add(result)
