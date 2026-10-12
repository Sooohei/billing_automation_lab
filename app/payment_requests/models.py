import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaymentRequestStatus(StrEnum):
    UNSUBMITTED = "unsubmitted"  # 未申請
    SUBMITTED = "submitted"  # 申請済


class PaymentRequestInput(Base):
    """支払い依頼インプット。請求書 1 件につき 1 件。削除しない。

    Output で必須の項目も、編集の途中では空がありうるので NULL 可とする。
    """

    __tablename__ = "payment_request_inputs"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), primary_key=True)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("partners.id"))
    title: Mapped[str | None] = mapped_column(Text)
    invoice_number: Mapped[str | None] = mapped_column(Text)
    qualified_invoice_issuer_number: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    amount_excluding_tax: Mapped[int | None] = mapped_column(BigInteger)
    tax_amount: Mapped[int | None] = mapped_column(BigInteger)
    amount_including_tax: Mapped[int | None] = mapped_column(BigInteger)
    freee_partner_id: Mapped[int | None] = mapped_column(BigInteger)
    freee_account_item_id: Mapped[int | None] = mapped_column(BigInteger)
    freee_tax_code: Mapped[int | None] = mapped_column(BigInteger)
    freee_approval_flow_route_id: Mapped[int | None] = mapped_column(BigInteger)
    # 紐付けた事前申請。申請番号と件名は、取得に失敗したときなどにも表示するための控え
    pre_application_id: Mapped[int | None] = mapped_column(BigInteger)
    pre_application_number: Mapped[str | None] = mapped_column(Text)
    pre_application_title: Mapped[str | None] = mapped_column(Text)
    # 作成時に SR-02 の抽出結果があったか
    created_from_extraction: Mapped[bool]
    status: Mapped[str] = mapped_column(Text, default=PaymentRequestStatus.UNSUBMITTED)
    freee_payment_request_id: Mapped[int | None] = mapped_column(BigInteger)
    applicant_email: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('unsubmitted', 'submitted')", name="status"),
        CheckConstraint(
            "status <> 'submitted' OR (freee_payment_request_id IS NOT NULL"
            " AND applicant_email IS NOT NULL AND applied_at IS NOT NULL)",
            name="submitted_fields",
        ),
    )

    @property
    def is_submitted(self) -> bool:
        return self.status == PaymentRequestStatus.SUBMITTED
