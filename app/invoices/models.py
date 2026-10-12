import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Invoice(Base):
    """請求書データ。PDF の添付ファイル 1 件につき 1 件。削除しない。"""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_key: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    sender_email: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    # SR-03 の一覧の絞り込みで使う
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    gmail_message_id: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("uq_invoices_file_sha256", "file_sha256", unique=True),)


class IngestedMessage(Base):
    """取込に成功したメール。ここにないメールが、次回の取込の対象になる。"""

    __tablename__ = "ingested_messages"

    gmail_message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
