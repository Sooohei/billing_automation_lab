import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Partner(Base):
    """取引先。削除は論理削除（deleted_at）。"""

    __tablename__ = "partners"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    freee_partner_id: Mapped[int] = mapped_column(BigInteger)
    freee_account_item_id: Mapped[int] = mapped_column(BigInteger)
    freee_tax_code: Mapped[int] = mapped_column(BigInteger)
    freee_approval_flow_route_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    emails: Mapped[list["PartnerEmail"]] = relationship(
        back_populates="partner", cascade="all, delete-orphan", order_by="PartnerEmail.id"
    )

    __table_args__ = (
        Index(
            "uq_partners_name_active",
            "name",
            unique=True,
            postgresql_where=deleted_at.is_(None),
        ),
    )


class PartnerEmail(Base):
    """送信元メールアドレス。有効な取引先のアドレスだけを置き、取引先の削除時は物理削除する。"""

    __tablename__ = "partner_emails"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("partners.id"), index=True)
    email: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    partner: Mapped[Partner] = relationship(back_populates="emails")

    __table_args__ = (Index("uq_partner_emails_email", "email", unique=True),)
