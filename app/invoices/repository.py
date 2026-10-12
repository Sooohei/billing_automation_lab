from sqlalchemy import select
from sqlalchemy.orm import Session

from app.invoices.models import IngestedMessage, Invoice


class InvoiceRepository:
    """請求書データと取込済みのメールの読み書き。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_ingested_message_ids(self, message_ids: list[str]) -> set[str]:
        """渡したメールの ID のうち、取込済みのもの。"""
        if not message_ids:
            return set()
        statement = select(IngestedMessage.gmail_message_id).where(
            IngestedMessage.gmail_message_id.in_(message_ids)
        )
        return set(self._session.scalars(statement))

    def find_existing_sha256s(self, sha256s: list[str]) -> set[str]:
        """渡した SHA-256 のうち、請求書データがすでにあるもの。"""
        if not sha256s:
            return set()
        statement = select(Invoice.file_sha256).where(Invoice.file_sha256.in_(sha256s))
        return set(self._session.scalars(statement))

    def add_invoice(self, invoice: Invoice) -> None:
        self._session.add(invoice)

    def add_ingested_message(self, message_id: str) -> None:
        self._session.add(IngestedMessage(gmail_message_id=message_id))
