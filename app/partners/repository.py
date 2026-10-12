import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.partners.models import Partner, PartnerEmail
from app.partners.normalize import normalize_email


class PartnerRepository:
    """取引先の読み出し。SR-01〜03 にも提供する。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_by_email(self, email: str) -> Partner | None:
        """送信元メールアドレス（正規化して照合）に対応する有効な取引先。なければ None。"""
        statement = (
            select(Partner)
            .join(PartnerEmail)
            .where(PartnerEmail.email == normalize_email(email), Partner.deleted_at.is_(None))
        )
        return self._session.scalars(statement).one_or_none()

    def list_active_emails(self) -> list[str]:
        """有効な取引先の送信元メールアドレスの一覧。"""
        statement = (
            select(PartnerEmail.email)
            .join(Partner)
            .where(Partner.deleted_at.is_(None))
            .order_by(PartnerEmail.email)
        )
        return list(self._session.scalars(statement))

    def list_active(self) -> list[Partner]:
        """有効な取引先を取引先名の順に返す。"""
        statement = (
            select(Partner)
            .where(Partner.deleted_at.is_(None))
            .options(selectinload(Partner.emails))
            .order_by(Partner.name)
        )
        return list(self._session.scalars(statement))

    def get_including_deleted(self, partner_id: uuid.UUID) -> Partner | None:
        """削除済みも含めて取引先を返す。"""
        return self._session.get(Partner, partner_id)
