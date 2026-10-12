import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExtractionResult(Base):
    """抽出結果。請求書データ 1 件につき 1 件。上書き・削除しない。

    抽出項目の値が NULL なら「読み取れず」、NULL でなければ「読み取り済」とする。
    """

    __tablename__ = "extraction_results"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), primary_key=True)
    # 送信元メールアドレスに対応する取引先。なければ NULL
    partner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("partners.id"))
    invoice_number: Mapped[str | None] = mapped_column(Text)
    qualified_invoice_issuer_number: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    amount_excluding_tax: Mapped[int | None] = mapped_column(BigInteger)
    tax_amount: Mapped[int | None] = mapped_column(BigInteger)
    amount_including_tax: Mapped[int | None] = mapped_column(BigInteger)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
